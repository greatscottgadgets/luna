#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Header Packet Rx-handling gateware. """

from nmigen                        import *
from usb_protocol.types.superspeed import LinkCommand

from .header                       import HeaderPacket, HeaderQueue
from .crc                          import compute_usb_crc5, HeaderPacketCRC
from .command                      import LinkCommandDetector
from ..physical.coding             import SHP, EPF, get_word_for_symbols
from ...stream                     import USBRawSuperSpeedStream

class RawHeaderPacketTransmitter(Elaboratable):
    """ Class that generates and sends

    This class performs the validations required at the link layer of the USB specification;
    which include checking the CRC-5 and CRC-16 embedded within the header packet.


    Attributes
    ----------
    source: USBRawSuperSpeedStream(), output stream
        Stream that carries the generated packets.

    packet: HeaderPacket(), input
        The header packet to be sent. The CRC fields do not need to be valid, and will
        be ignored and replaced with a computed CRC>

    generate: Signal(), input
        Strobe; indicates that a link command should be generated.
    done: Signal(), output
        Indicates that the link command will be complete this cycle; and thus this unit will
        be ready to send another link command next cycle.
    """

    def __init__(self):

        #
        # I/O port.
        #
        self.source   = USBRawSuperSpeedStream()

        self.packet   = HeaderPacket()

        self.generate = Signal()
        self.done     = Signal()


    def elaborate(self, platform):
        m = Module()

        source = self.source
        packet = HeaderPacket()

        #
        # CRC-16 Generator
        #
        m.submodules.crc16 = crc16 = HeaderPacketCRC()
        m.d.comb += crc16.data_input.eq(source.data),

        #
        # Packet transmitter.
        #
        with m.FSM(domain="ss"):

            # IDLE -- wait for a generate command
            with m.State("IDLE"):
                # Don't start our CRC until we're past our HPSTART header.
                m.d.comb += crc16.clear.eq(1)

                # Once we have a request, latch in our data, and start sending.
                with m.If(self.generate):
                    m.d.ss += packet.eq(self.packet)
                    m.next = "SEND_HPSTART"


            # SEND_HPSTART -- send our "start-of-header-packet" marker.
            with m.State("SEND_HPSTART"):

                # Drive the bus with our header...
                header_data, header_ctrl = get_word_for_symbols(SHP, SHP, SHP, EPF)
                m.d.comb += [
                    source.valid  .eq(1),
                    source.data   .eq(header_data),
                    source.ctrl   .eq(header_ctrl),
                ]

                # ... and keep driving it until it's accepted.
                with m.If(source.ready):
                    m.next = "SEND_DW0"


            # SEND_DWn -- send along the three first data words unalatered, as we don't
            # need to fill in any CRC details, here.
            data_words = [packet.dw0, packet.dw1, packet.dw2]
            for n in range(3):
                with m.State(f"SEND_DW{n}"):

                    # Drive the bus with the relevant data word...
                    m.d.comb += [
                        source.valid  .eq(1),
                        source.data   .eq(data_words[n]),
                        source.ctrl   .eq(0),
                    ]

                    # ... and keep driving it until it's accepted.
                    with m.If(source.ready):
                        m.d.comb += crc16.advance_crc.eq(1)
                        m.next = f"SEND_DW{n + 1}"


            # Compose our final data word from our individual fields, filling
            with m.State(f"SEND_DW3"):

                # Compose our data word
                m.d.comb += [
                    source.valid        .eq(1),
                    source.data[ 0:16]  .eq(crc16.crc),
                    source.data[16:19]  .eq(packet.sequence_number),
                    source.data[19:22]  .eq(packet.dw3_reserved),
                    source.data[22:25]  .eq(packet.hub_depth),
                    source.data[25]     .eq(packet.deferred),
                    source.data[26]     .eq(packet.delayed),
                    source.data[27:32]  .eq(compute_usb_crc5(source.data[16:27])),
                    source.ctrl         .eq(0)
                ]

                # Once this final word is accepted, we're done!
                with m.If(source.ready):
                    m.d.comb += self.done.eq(1)
                    m.next = f"IDLE"

        return m



class HeaderPacketTransmitter(Elaboratable):
    """ Transmitter-side Header Packet logic.

    This module handles all header-packet-transmission related logic for the link layer; including
    header packet generation, partner buffer tracking / flow control, and link command reception.

    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input stream [monitor only]
        Stream that monitors the data received on the physical layer for link commands.
    source: USBRawSuperSpeedStream(), output stream
        Stream that carries our transmissions down to the physical layer.

    enable: Signal(), input
        When asserted, this unit will be enabled; and will be allowed to start transmitting.

    queue: HeaderQueue(), input stream
        Stream of header packets received received from the protocol layer to be transmitted.

    retry_received: Signal(), output
        Strobe; pulsed high when we receive a link retry request.
    retry_required: Signal(), output
        Strobe; pulsed high when we need to send a retry request.

    recovery_required: Signal(), output
        Strobe; pulsed when a condition that requires link recovery occurs.
    """

    SEQUENCE_NUMBER_WIDTH = 3

    def __init__(self, *, buffer_count=4, ss_clock_frequency=125e6):
        self._buffer_count    = buffer_count
        self._clock_frequency = ss_clock_frequency

        #
        # I/O port
        #
        self.sink                  = USBRawSuperSpeedStream()
        self.source                = USBRawSuperSpeedStream()

        # Simple controls.
        self.enable                = Signal()
        self.bringup_complete      = Signal()

        # Protocol layer interface.
        self.queue                 = HeaderQueue()

        # Event interface.
        self.link_command_received = Signal()
        self.retry_received        = Signal()
        self.retry_required        = Signal()
        self.recovery_required     = Signal()

        # Debug information.
        self.credits_available     = Signal(range(self._buffer_count + 1))
        self.packets_to_send       = Signal(range(self._buffer_count + 1))


    def elaborate(self, platform):
        m = Module()

        #
        # Credit tracking.
        #

        # Keep track of how many transmit credits we currently have.
        credits_available    = Signal(range(self._buffer_count + 1))
        credit_received      = Signal()
        credit_consumed      = Signal()

        with m.If(credit_received & ~credit_consumed):
            m.d.ss += credits_available.eq(credits_available + 1)
        with m.Elif(credit_consumed & ~credit_received):
            m.d.ss += credits_available.eq(credits_available - 1)


        # Provide a flag that indicates when we're done with our full bringup.
        with m.If(self.enable == 0):
            m.d.ss += self.bringup_complete.eq(0)
        with m.Elif(credits_available == self._buffer_count):
            m.d.ss += self.bringup_complete.eq(1)


        #
        # Task "queues".
        #

        # Control signals.
        retire_packet     = Signal()

        # Pending packet count.
        packets_to_send      = Signal(range(self._buffer_count + 1))
        enqueue_send         = Signal()
        dequeue_send         = Signal()

        # Unretired packet count.
        packets_awaiting_ack = Signal()

        # If we need to retry sending our packets, we'll need to reset our pending packet count.
        # Otherwise, we increment and decrement our "to send" counts normally.
        with m.If(self.retry_required):
            m.d.ss += packets_to_send.eq(packets_awaiting_ack)
        with m.Elif(enqueue_send & ~dequeue_send):
            m.d.ss += packets_to_send.eq(packets_to_send + 1)
        with m.Elif(dequeue_send & ~enqueue_send):
            m.d.ss += packets_to_send.eq(packets_to_send - 1)

        # Track how many packets are yet to be retired.
        with m.If(enqueue_send & ~retire_packet):
            m.d.ss += packets_awaiting_ack.eq(packets_awaiting_ack + 1)
        with m.Elif(retire_packet & ~enqueue_send & packets_awaiting_ack > 0):
            m.d.ss += packets_awaiting_ack.eq(packets_awaiting_ack - 1)


        #
        # Header Packet Buffers
        #

        # Track:
        # - which buffer should be filled next
        # - which buffer we should send from next
        # - which buffer we've last acknowledged
        read_pointer      = Signal(range(self._buffer_count))
        write_pointer     = Signal.like(read_pointer)
        ack_pointer       = Signal.like(read_pointer)

        # Create buffers to receive any incoming header packets.
        buffers = Array(HeaderPacket() for _ in range(self._buffer_count))

        # If we need to retry sending our packets, we'll need to start reading
        # again from the last acknowledged packet; so we'll reset our read pointer.
        with m.If(self.retry_required):
            m.d.ss += read_pointer.eq(ack_pointer)
        with m.Elif(dequeue_send):
            m.d.ss += read_pointer.eq(read_pointer + 1)

        # Last ACK'd buffer / packet retirement tracker.
        with m.If(retire_packet):
            m.d.ss += ack_pointer.eq(ack_pointer + 1)


        #
        # Packet acceptance (protocol layer -> link layer).
        #

        # If we have link credits available, we're able to accept data from the protocol layer.
        m.d.comb += self.queue.ready.eq(credits_available != 0)


        # If the protocol layer is handing us a packet...
        with m.If(self.queue.valid & self.queue.ready):
            # ... consume a credit, as we're going to be using up a receiver buffer, and
            # schedule sending of that packet.
            m.d.comb += [
                credit_consumed  .eq(1),
                enqueue_send     .eq(1)
            ]

            # Finally, capture the packet into the buffer for transmission.
            m.d.ss += [
                buffers[write_pointer]  .eq(self.queue.header),
                write_pointer           .eq(write_pointer + 1)
            ]


        #
        # Packet delivery (link layer -> physical layer)
        #
        m.submodules.packet_tx = packet_tx = RawHeaderPacketTransmitter()
        m.d.comb += self.source.stream_eq(packet_tx.source)

        # Keep track of the next sequence number we'll need to send...
        transmit_sequence_number = Signal(self.SEQUENCE_NUMBER_WIDTH)

        with m.FSM(domain="ss"):

            # DISPATCH_PACKET -- wait packet transmissions to be scheduled, and prepare
            # our local transmitter with the proper data to send them.
            with m.State("DISPATCH_PACKET"):

                # If we have packets to send, pass them to our transmitter.
                with m.If(packets_to_send & self.enable):
                    m.d.ss += [
                        # Grab the packet from our read queue, and pass it to the transmitter;
                        # but override its sequence number field with our current sequence number.
                        packet_tx.packet                  .eq(buffers[read_pointer]),
                        packet_tx.packet.sequence_number  .eq(transmit_sequence_number),
                    ]

                    # Move on to sending our packet.
                    m.next = "WAIT_FOR_SEND"


            # WAIT_FOR_SEND -- we've now dispatched our packet; and we're ready to wait for it to be sent.
            with m.State("WAIT_FOR_SEND"):
                m.d.comb += packet_tx.generate.eq(1)

                # Once the packet is done...
                with m.If(packet_tx.done):
                    m.d.comb += dequeue_send.eq(1)
                    m.d.ss   += transmit_sequence_number.eq(transmit_sequence_number + 1)

                    # If this was the last packet we needed to send, resume waiting for one.
                    with m.If(packets_to_send == 1):
                        m.next = "DISPATCH_PACKET"


        #
        # Header Packet Timer
        #
        # FIXME: implement this



        #
        # Link Command Handling
        #

        # Core link command receiver.
        m.submodules.lc_detector = lc_detector = LinkCommandDetector()
        m.d.comb += [
            lc_detector.sink            .tap(self.sink),
            self.link_command_received  .eq(lc_detector.new_command)
        ]

        # Keep track of which credit we expect to get back next.
        next_expected_credit = Signal(range(self._buffer_count))

        # Keep track of what sequence number we expect to have ACK'd next.
        next_expected_ack_number = Signal(self.SEQUENCE_NUMBER_WIDTH, reset=-1)

        # Handle link commands as we receive them.
        with m.If(lc_detector.new_command):
            with m.Switch(lc_detector.command):

                #
                # Link Credit Reception
                #
                with m.Case(LinkCommand.LCRD):

                    # If the credit matches the sequence we're expecting, we can accept it!
                    with m.If(next_expected_credit == lc_detector.subtype):
                        m.d.comb += credit_received.eq(1)

                        # Next time, we'll expect the next credit in the sequence.
                        m.d.ss += next_expected_credit.eq(next_expected_credit + 1)

                    # Otherwise, we've lost synchronization. We'll need to trigger link recovery.
                    with m.Else():
                        m.d.comb += self.recovery_required.eq(1)

                #
                # Packet Acknowledgement
                #
                with m.Case(LinkCommand.LGOOD):

                    # If the credit matches the sequence we're expecting, we can accept it!
                    with m.If(next_expected_ack_number == lc_detector.subtype):
                        m.d.comb += retire_packet.eq(1)

                        # Next time, we'll expect the next credit in the sequence.
                        m.d.ss += next_expected_ack_number.eq(next_expected_ack_number + 1)

                    # Otherwise, we've lost synchronization. We'll need to trigger link recovery.
                    with m.Else():
                        m.d.comb += self.recovery_required.eq(1)


                #
                # Packet Negative Acknowledgement
                #
                with m.Case(LinkCommand.LBAD):

                    # LBADs aren't sequenced; instead, they require a retry of all unacknowledged
                    # (unretired) packets. Mark ourselves as requiring a retry; which should trigger
                    # our internal logic to execute a retry.
                    m.d.comb += self.retry_required.eq(1)


                #
                # Link Partner Retrying Send
                #
                with m.Case(LinkCommand.LRTY):

                    # If we see an LRTY, it's an indication that our link partner is performing a
                    # retried send. This information is handled by the Reciever, so we'll forward it along.
                    m.d.comb += self.retry_received.eq(1)


        #
        # Debug outputs.
        #
        m.d.comb += [
            self.credits_available  .eq(credits_available),
            self.packets_to_send    .eq(packets_to_send)
        ]



        return m
