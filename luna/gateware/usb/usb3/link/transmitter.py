#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Packet transmission handling gateware. """

from amaranth                      import *
from usb_protocol.types.superspeed import LinkCommand, HeaderPacketType

from .header                       import HeaderPacket, HeaderQueue
from .crc                          import compute_usb_crc5, HeaderPacketCRC, DataPacketPayloadCRC
from .command                      import LinkCommandDetector
from ..physical.coding             import SHP, SDP, EPF, END, EDB, get_word_for_symbols
from ...stream                     import USBRawSuperSpeedStream, SuperSpeedStreamInterface



class RawPacketTransmitter(Elaboratable):
    """ Class that generates and sends header packets; with an optional payload attached.

    This class generates the checks required at the link layer of the USB specification;
    which include checking the CRC-5 and CRC-16 embedded within the header packet, and
    the CRC-32 embedded within any associated payloads.


    Attributes
    ----------
    source: USBRawSuperSpeedStream(), output stream
        Stream that carries the generated packets.

    header: HeaderPacket(), input
        The header packet to be sent. The CRC fields do not need to be valid, and will
        be ignored and replaced with a computed CRC. If the header packet is of type data,
        :attr:``data_sink`` will be allowed to provide a follow-up Data Packet Payload.
    data_sink: SuperSpeedStreamInterface(), input stream
        If the provided :attr:``header`` is a Data Header, and :attr:``data_sink`` is valid
        when the packet's transmission is sent, this data stream will be used to provide a
        follow-up Data Packet Payload.

    generate: Signal(), input
        Strobe; indicates that a packet should be generated.
    done: Signal(), output
        Indicates that the packet will be complete this cycle; and thus this unit will
        be ready to send another packet next cycle.
    """

    def __init__(self):

        #
        # I/O port.
        #
        self.source    = USBRawSuperSpeedStream()

        # Packet data in.
        self.header    = HeaderPacket()
        self.data_sink = SuperSpeedStreamInterface()

        self.generate  = Signal()
        self.done      = Signal()


    def elaborate(self, platform):
        m = Module()

        # Shorthands.
        source    = self.source
        data_sink = self.data_sink

        # Latched data.
        header    = HeaderPacket()

        #
        # CRC Generators
        #

        # CRC-16, for header packets
        m.submodules.crc16 = crc16 = HeaderPacketCRC()
        m.d.comb += crc16.data_input.eq(source.data)

        # CRC-32, for payload packets
        m.submodules.crc32 = crc32 = DataPacketPayloadCRC()
        m.d.comb += [
            crc32.data_input    .eq(self.data_sink.data),

            # Advance our CRC32 whenever we accept data from our sink,
            # according to how many bytes are currently valid.
            crc32.advance_word  .eq((data_sink.valid == 0b1111) & data_sink.ready),
            crc32.advance_3B    .eq((data_sink.valid == 0b0111) & data_sink.ready),
            crc32.advance_2B    .eq((data_sink.valid == 0b0011) & data_sink.ready),
            crc32.advance_1B    .eq((data_sink.valid == 0b0001) & data_sink.ready),
        ]


        #
        # Packet transmitter.
        #

        # Create a time-delayed version of our data; so we can always work with data from
        # a single cycle ago. This allows us to compute our CRC before we need to send it;
        # which is important, as a CRC can start in the middle of a word (and thus needs to
        # factor in data available the same cycle as the CRC is sent).
        pipelined_data_word  = Signal.like(self.data_sink.data)
        pipelined_data_valid = Signal.like(self.data_sink.valid)

        # Store whether our packet is a ZLP.
        packet_is_zlp = Signal()

        with m.FSM(domain="ss"):

            # IDLE -- wait for a generate command
            with m.State("IDLE"):
                # Don't start our CRCs until we're sending the data section relevant to them.
                m.d.comb += [
                    crc16.clear  .eq(1),
                    crc32.clear  .eq(1)
                ]

                # Once we have a request, latch in our data, and start sending.
                with m.If(self.generate):
                    m.d.ss += header.eq(self.header)
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
            data_words = [header.dw0, header.dw1, header.dw2]
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
            with m.State("SEND_DW3"):

                # Compose our data word
                m.d.comb += [
                    source.valid        .eq(1),
                    source.data[ 0:16]  .eq(crc16.crc),
                    source.data[16:19]  .eq(header.sequence_number),
                    source.data[19:22]  .eq(header.dw3_reserved),
                    source.data[22:25]  .eq(header.hub_depth),
                    source.data[25]     .eq(header.delayed),
                    source.data[26]     .eq(header.deferred),
                    source.data[27:32]  .eq(compute_usb_crc5(source.data[16:27])),
                    source.ctrl         .eq(0)
                ]

                # Once our final header packet word has been sent; decide what to do next.
                with m.If(source.ready):

                    # If we just sent a data packet header, and we have a valid data-stream,
                    # or if we're sending a ZLP, follow on immediately with a Data Packet Payload.
                    was_data_header = (header.dw0[ 0: 4] == HeaderPacketType.DATA)
                    with m.If(was_data_header):
                        m.d.ss += packet_is_zlp.eq(self.data_sink.valid == 0)
                        m.next = "START_DPP"

                    # Otherwise, we're done!
                    with m.Else():
                        m.d.comb += self.done.eq(1)
                        m.next = f"IDLE"


            # START_DPP -- we'll start our data packet payload with our framing;
            # and prepare to send our actual payload.
            with m.State("START_DPP"):

                # Send our start framing...
                header_data, header_ctrl = get_word_for_symbols(SDP, SDP, SDP, EPF)
                m.d.comb += [
                    source.valid  .eq(1),
                    source.data   .eq(header_data),
                    source.ctrl   .eq(header_ctrl),
                ]

                with m.If(source.ready):

                    # Special case: if we're retransmitting a data packet, we'll abort it immediately,
                    # since we don't have the data buffered anywhere. Retransmission of the data payload
                    # will be handled at the protocol layer.
                    with m.If(header.delayed):
                        m.next = "ABORT_DPP"

                    # Special case: if we're sending a ZLP, we'll jump directly to sending our CRC.
                    with m.Elif(packet_is_zlp):

                        # We'll treat this as though we'd just sent a full data word; as this indicates
                        # to our later states that our data was word-aligned. (0B is a multiple of 4, after all.)
                        m.d.ss += pipelined_data_valid.eq(0b1111)
                        m.next = "SEND_CRC"

                    # Otherwise, we have some data to handle.
                    with m.Else():

                        # Capture the first word of our data-to-send into our pipeline...
                        m.d.ss   += [
                            pipelined_data_word   .eq(self.data_sink.data),
                            pipelined_data_valid  .eq(self.data_sink.valid)
                        ]

                        # ... and accept that data, so our sender moves on to the next word.
                        m.d.comb += self.data_sink.ready.eq(1)

                        # ... and as long as we didn't just capture the last word, start the actual
                        # payload transmission.
                        with m.If(~self.data_sink.last):
                            m.next = "SEND_PAYLOAD"

                        # If we -did- just capture the last word, we can skip to our last-word handler.
                        with m.Else():
                            m.next = "SEND_LAST_WORD"


            # SEND_PAYLOAD -- send the core part of our data stream.
            with m.State("SEND_PAYLOAD"):

                # We'll always send our last pipelined value; so we can always have a valid "last word"
                # for our last word handler, which handles special cases like inserting our CRC.
                m.d.comb += [
                    source.data         .eq(pipelined_data_word),
                    source.valid        .eq(1),
                ]

                # Each time one of the words we're transmitting is accepted, we'll in turn accept a new
                # word into our pipeline register.
                with m.If(source.ready):
                    m.d.comb += self.data_sink.ready.eq(1)
                    m.d.ss   += [
                        pipelined_data_word   .eq(self.data_sink.data),
                        pipelined_data_valid  .eq(self.data_sink.valid)
                    ]

                    # When we're finally receiving our last packet, we're also finished computing our CRC.
                    # This means we can move on safely to sending our pipelined word; knowing we're ready to
                    # send part of our CRC if the last word isn't fully aligned.
                    with m.If(data_sink.last):
                        m.next = "SEND_LAST_WORD"


            # SEND_LAST_WORD -- flush our pipeline; and send our final word.
            # Our final word is a special case; as it may not be a full word; in which
            # case we'll have to stick part of our CRC into it.
            with m.State("SEND_LAST_WORD"):

                # Send the final value captured from our pipeline; which we may modify slightly below.
                m.d.comb += [
                    source.data         .eq(pipelined_data_word),
                    source.valid        .eq(1),
                ]

                # If we didn't capture a full word, we'll need to stick pieces of our final CRC
                # into the unused/invalid sections of our data. We'll do so, selecting our position
                # based on how many bytes of valid data we're sending.
                with m.Switch(pipelined_data_valid):

                    # 3 valid bytes, 1 byte of CRC
                    with m.Case (0b0111):
                        m.d.comb += source.data[24:32].eq(crc32.crc[0:8])

                    # 2 valid bytes, 2 bytes of CRC
                    with m.Case (0b0011):
                        m.d.comb += source.data[16:32].eq(crc32.crc[0:16])

                    # 1 valid byte, 3 bytes of CRC
                    with m.Case (0b0001):
                        m.d.comb += source.data[8:32].eq(crc32.crc[0:24])


                # Once our last data word is accepted, move to sending the (remainder) of the CRC.
                with m.If(source.ready):
                    m.next = "SEND_CRC"


            # SEND_CRC -- send the CRC (or what remains of it)
            with m.State("SEND_CRC"):
                m.d.comb += source.valid.eq(1)

                # We'll need to send however much of the CRC is left; which will depend on the validity
                # of the final byte we had pipelined.
                with m.Switch(pipelined_data_valid):

                    # If our data packet was word aligned, we've sent no CRC bytes.
                    # Send our full word.
                    with m.Case(0b1111):
                        m.d.comb += [
                            source.data  .eq(crc32.crc),
                            source.ctrl  .eq(0)
                        ]

                    # If we had three valid bytes of data last time, we've sent one byte of CRC.
                    # Send the other three, followed by one END framing word.
                    with m.Case(0b0111):
                        m.d.comb += [
                            source.data  .eq(Cat(crc32.crc[8:32], END.value_const())),
                            source.ctrl  .eq(0b1000),
                        ]

                    # Same, but for 2B valid and 2B CRC
                    with m.Case(0b0011):
                        m.d.comb += [
                            source.data  .eq(Cat(crc32.crc[16:32], END.value_const(repeat=2))),
                            source.ctrl  .eq(0b1100),
                        ]

                    # Same, but for 1B valid and 3B CRC
                    with m.Case(0b0001):
                        m.d.comb += [
                            source.data  .eq(Cat(crc32.crc[24:32], END.value_const(repeat=3))),
                            source.ctrl  .eq(0b1110),
                        ]


                # Once our CRC is accepted, finish our payload.
                with m.If(source.ready):
                    m.next = "FINISH_DPP"


            # FINISH_DPP -- send our end-of-payload framing.
            with m.State("FINISH_DPP"):
                m.d.comb += source.valid.eq(1)

                # Get our data and ctrl constants for our framing.
                framing_data, framing_ctrl = get_word_for_symbols(END, END, END, EPF)

                # We'll need to send however much of the framing is left; which will depend on the
                # where our CRC ended.
                with m.Switch(pipelined_data_valid):

                    # If our data packet was word aligned, we've sent no CRC bytes.
                    # Send our full word.
                    with m.Case(0b1111):
                        m.d.comb += [
                            source.data         .eq(framing_data),
                            source.ctrl         .eq(framing_ctrl),
                        ]

                    # If we had three valid bytes of data last time, we've sent one byte of framing.
                    # Send the other three, followed by zeroes (logical IDL).
                    with m.Case(0b0111):
                        m.d.comb += [
                            source.data         .eq(framing_data[8:]),
                            source.ctrl         .eq(framing_ctrl[1:]),
                        ]

                    # Same, but 2B frame and 2B IDL.
                    with m.Case(0b0011):
                        m.d.comb += [
                            source.data         .eq(framing_data[16:]),
                            source.ctrl         .eq(framing_ctrl[ 2:]),
                        ]

                    # Same, but 1B frame and 3B IDL.
                    with m.Case(0b0001):
                        m.d.comb += [
                            source.data         .eq(framing_data[24:]),
                            source.ctrl         .eq(framing_ctrl[ 3:]),
                        ]


                # Once our CRC is accepted, finish our payload.
                with m.If(source.ready):
                    m.d.comb += self.done.eq(1)
                    m.next = "IDLE"


            # ABORT_DPP -- send our abort-of-payload framing.
            with m.State("ABORT_DPP"):

                # Send our abort framing...
                framing_data, framing_ctrl = get_word_for_symbols(EDB, EDB, EDB, EPF)
                m.d.comb += [
                    source.valid  .eq(1),
                    source.data   .eq(framing_data),
                    source.ctrl   .eq(framing_ctrl),
                ]

                # Once our framing is accepted, finish our payload.
                with m.If(source.ready):
                    m.d.comb += self.done.eq(1)
                    m.next = "IDLE"

        return m



class PacketTransmitter(Elaboratable):
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

    lgo_received: Signal(), output
        Strobe; indicates that we've received a request to move to a new power state.
    lgo_target; Signal(2), output
        Indicates the power-state associated with a given LGO event; valid when :attr:``lgo_received``
        is asserted.

    recovery_required: Signal(), output
        Strobe; pulsed when a condition that requires link recovery occurs.
    """

    SEQUENCE_NUMBER_WIDTH = 3

    CREDIT_TIMEOUT = 5e-3

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
        self.usb_reset             = Signal()
        self.bringup_complete      = Signal()

        # Protocol layer interface.
        self.queue                 = HeaderQueue()
        self.data_sink             = SuperSpeedStreamInterface()

        # Event interface.
        self.link_command_received = Signal()
        self.retry_received        = Signal()
        self.retry_required        = Signal()
        self.lrty_pending          = Signal()
        self.recovery_required     = Signal()

        self.lgo_received          = Signal()
        self.lgo_target            = Signal(2)

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


        #
        # Task "queues".
        #

        # Control signals.
        retire_packet     = Signal()

        # Pending packet count.
        packets_to_send      = Signal(range(self._buffer_count + 1))
        enqueue_send         = Signal()
        dequeue_send         = Signal()

        # Un-retired packet count.
        packets_awaiting_ack = Signal(range(self._buffer_count + 1))

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
        with m.Elif(retire_packet & ~enqueue_send & (packets_awaiting_ack != 0)):
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

        # Keep track of the next sequence number we'll need to assign.
        transmit_sequence_number = Signal(self.SEQUENCE_NUMBER_WIDTH)

        # If we have link credits available, we're able to accept data from the protocol layer.
        m.d.comb += self.queue.ready.eq(self.bringup_complete & (credits_available != 0))

        # If the protocol layer is handing us a packet...
        with m.If(self.queue.valid & self.queue.ready):
            # ... consume a credit, as we're going to be using up a receiver buffer, and
            # schedule sending of that packet.
            m.d.comb += [
                credit_consumed  .eq(1),
                enqueue_send     .eq(1)
            ]

            # Assign the packet a sequence number, and capture it into the buffer for transmission.
            # [USB3.0r1: 7.2.4.1.1]: "A header packet that is re-transmitted shall maintain its
            # originally assigned Header Sequence Number."
            m.d.ss += [
                buffers[write_pointer]                  .eq(self.queue.header),
                buffers[write_pointer].sequence_number  .eq(transmit_sequence_number),
                write_pointer                           .eq(write_pointer + 1),
                transmit_sequence_number                .eq(transmit_sequence_number + 1)
            ]


        #
        # Packet delivery (link layer -> physical layer)
        #
        m.submodules.packet_tx = packet_tx = RawPacketTransmitter()
        m.d.comb += [
            packet_tx.header     .eq(buffers[read_pointer]),
            packet_tx.data_sink  .stream_eq(self.data_sink),
            self.source          .stream_eq(packet_tx.source)
        ]


        # Keep track of whether a retry has been requested.
        retry_pending = Signal()
        with m.If(self.retry_required):
            m.d.ss += retry_pending.eq(1)


        with m.FSM(domain="ss"):

            # DISPATCH_PACKET -- wait packet transmissions to be scheduled, and prepare
            # our local transmitter with the proper data to send them.
            with m.State("DISPATCH_PACKET"):

                # If we have packets to send, pass them to our transmitter.
                with m.If(self.bringup_complete & (packets_to_send != 0)):

                    with m.If(~retry_pending):
                        # Wait until the packet is sent.
                        m.next = "WAIT_FOR_SEND"

                    with m.Else():
                        # Wait until all of the non-acknowledged packets are retransmitted.
                        m.next = "WAIT_FOR_RETRY"


            # WAIT_FOR_SEND -- we've now dispatched our packet; and we're ready to wait for it to be sent.
            with m.State("WAIT_FOR_SEND"):
                m.d.comb += packet_tx.generate.eq(1)

                # We're done with this packet.
                with m.If(packet_tx.done):

                    # If we received an LBAD in the meantime, our read pointer and counter are already
                    # set up for retransmission; don't touch them.
                    with m.If(~retry_pending):
                        m.d.comb += dequeue_send.eq(1)

                    # Handle the next packet, or wait for one.
                    m.next = "DISPATCH_PACKET"


            # WAIT_FOR_RETRY -- we're retransmitting all of the non-acknowledged packets, with the DL bit set;
            # but only after the receiver transmits LRTY.
            with m.State("WAIT_FOR_RETRY"):
                m.d.comb += packet_tx.header.delayed.eq(1)
                m.d.comb += packet_tx.generate.eq(~self.lrty_pending)

                # We're done with this packet.
                with m.If(packet_tx.done):
                    m.d.comb += dequeue_send.eq(1)

                    # If this was the last packet to retransmit, we're done handling this LBAD.
                    with m.If(packets_to_send == 1):
                        m.d.ss += retry_pending.eq(0)
                        m.next = "DISPATCH_PACKET"


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

                    # If we've received a Header Sequence Number Advertisement, update our sequence
                    # numbers, and indicate we're done with bringup.
                    with m.If(~self.bringup_complete):
                        m.d.ss += [
                            self.bringup_complete     .eq(1),

                            next_expected_ack_number  .eq(lc_detector.subtype + 1),
                            transmit_sequence_number  .eq(lc_detector.subtype + 1)
                        ]

                    # If the credit matches the sequence we're expecting, we can accept it!
                    with m.Elif(next_expected_ack_number == lc_detector.subtype):
                        m.d.comb += retire_packet.eq(1)

                        # Next time, we'll expect the next credit in the sequence.
                        m.d.ss += next_expected_ack_number.eq(next_expected_ack_number + 1)

                    # Otherwise, if we're expecting a packet, we've lost synchronization.
                    # We'll need to trigger link recovery.
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
                    # retried send. This information is handled by the Receiver, so we'll forward it along.
                    m.d.comb += self.retry_received.eq(1)


                #
                # Link Power State transition request.
                #
                with m.Case(LinkCommand.LGO_U):

                    # We don't handle LGO requests locally; so instead, we'll pass this back to the link layer.
                    m.d.comb += [
                        self.lgo_received  .eq(1),
                        self.lgo_target    .eq(lc_detector.subtype)
                    ]


        #
        # Header Packet Timer
        #

        # To ensure that a header packet buffer is never held by the receiver for too long
        # the USB3 specification requires us to automatically enter recovery if a credit is
        # outstanding for more than 5ms [USB3.2r1: 7.2.4.1.13]. We'll create a timer that can
        # count to this timeout.
        credit_timeout_cycles = int((self.CREDIT_TIMEOUT * self._clock_frequency + 1))
        pending_hp_timer = Signal(range(credit_timeout_cycles + 1))

        # Each time we receive a link credit and retire its packet, we'll re-start our timer.
        with m.If(retire_packet):
            m.d.ss += pending_hp_timer.eq(0)

        # If we don't have any outstanding packets, we'll clear our timer.
        with m.Elif((packets_awaiting_ack == 0) | ~self.enable):
            m.d.ss += pending_hp_timer.eq(0)

        # Otherwise, we'll count how many cycles we've had a credit outstanding for.
        with m.Else():
            m.d.ss += pending_hp_timer.eq(pending_hp_timer + 1)


        # If we ever reach our timeout, we'll need to trigger recovery.
        with m.If(pending_hp_timer == credit_timeout_cycles):
            m.d.comb += self.recovery_required.eq(1)


        #
        # Reset Handling
        #
        with m.If(~self.enable):
            m.d.ss += [
                self.bringup_complete     .eq(0),

                next_expected_credit      .eq(0),
                credits_available         .eq(0),

                packets_to_send           .eq(0),
                packets_awaiting_ack      .eq(0),
                read_pointer              .eq(0),
                write_pointer             .eq(0),
                ack_pointer               .eq(0),
                retry_pending             .eq(0),
            ]


        #
        # Debug outputs.
        #
        m.d.comb += [
            self.credits_available  .eq(credits_available),
            self.packets_to_send    .eq(packets_to_send)
        ]



        return m
