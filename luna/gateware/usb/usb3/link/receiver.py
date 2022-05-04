#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Header Packet Rx-handling gateware. """

import unittest

from amaranth                      import *
from amaranth.hdl.ast              import Fell

from usb_protocol.types.superspeed import LinkCommand

from .header                       import HeaderPacket, HeaderQueue
from .crc                          import compute_usb_crc5, HeaderPacketCRC
from .command                      import LinkCommandGenerator
from ..physical.coding             import SHP, EPF, stream_matches_symbols
from ...stream                     import USBRawSuperSpeedStream

from ....test.utils                import LunaSSGatewareTestCase, ss_domain_test_case



class RawHeaderPacketReceiver(Elaboratable):
    """ Class that monitors the USB bus for Header Packet, and receives them.

    This class performs the validations required at the link layer of the USB specification;
    which include checking the CRC-5 and CRC-16 embedded within the header packet.


    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input (monitor only)
        Stream that the USB data to be monitored.
    packet: HeaderPacket(), output
        The de-serialized form of our header packet.

    new_packet: Signal(), output
        Strobe; indicates that a new, valid header packet has been received. The new
        packet is now available on :attr:``packet``.
    bad_packet: Signal(), output
        Strobe; indicates that a corrupted, invalid header packet has been received.
        :attr:``packet`` has not been updated.

    expected_sequence: Signal(3), input
        Indicates the next expected sequence number; used to validate the received packet.

    """

    def __init__(self):

        #
        # I/O port
        #
        self.sink              = USBRawSuperSpeedStream()

        # Header packet output.
        self.packet            = HeaderPacket()

        # State indications.
        self.new_packet        = Signal()
        self.bad_packet        = Signal()

        # Sequence tracking.
        self.expected_sequence = Signal(3)
        self.bad_sequence      = Signal()


    def elaborate(self, platform):
        m = Module()

        sink   = self.sink

        # Store our header packet in progress; which we'll output only once it's been validated.
        packet = HeaderPacket()

        # Cache our expected CRC5, so we can pipeline generation and comparison.
        expected_crc5 = Signal(5)

        # Keep our "new packet" signal de-asserted unless asserted explicitly.
        m.d.ss += self.new_packet.eq(0)

        #
        # CRC-16 Generator
        #
        m.submodules.crc16 = crc16 = HeaderPacketCRC()
        m.d.comb += crc16.data_input.eq(sink.data),


        #
        # Receiver Sequencing
        #
        with m.FSM(domain="ss"):

            # WAIT_FOR_HPSTART -- we're currently waiting for HPSTART framing, which indicates
            # that the following 16 symbols (4 words) will be a header packet.
            with m.State("WAIT_FOR_HPSTART"):

                # Don't start our CRC until we're past our HPSTART header.
                m.d.comb += crc16.clear.eq(1)

                is_hpstart = stream_matches_symbols(sink, SHP, SHP, SHP, EPF)
                with m.If(is_hpstart):
                    m.next = "RECEIVE_DW0"

            # RECEIVE_DWn -- the first three words of our header packet are data words meant form
            # the protocol layer; we'll receive them so we can pass them on to the protocol layer.
            for n in range(3):
                with m.State(f"RECEIVE_DW{n}"):

                    with m.If(sink.valid):
                        m.d.comb += crc16.advance_crc.eq(1)
                        m.d.ss += packet[f'dw{n}'].eq(sink.data)
                        m.next = f"RECEIVE_DW{n+1}"

            # RECEIVE_DW3 -- we'll receive and parse our final data word, which contains the fields
            # relevant to the link layer.
            with m.State("RECEIVE_DW3"):

                with m.If(sink.valid):
                    m.d.ss += [
                        # Collect the fields from the DW...
                        packet.crc16            .eq(sink.data[ 0:16]),
                        packet.sequence_number  .eq(sink.data[16:19]),
                        packet.dw3_reserved     .eq(sink.data[19:22]),
                        packet.hub_depth        .eq(sink.data[22:25]),
                        packet.delayed          .eq(sink.data[25]),
                        packet.deferred         .eq(sink.data[26]),
                        packet.crc5             .eq(sink.data[27:32]),

                        # ... and pipeline a CRC of the to the link control word.
                        expected_crc5           .eq(compute_usb_crc5(sink.data[16:27]))
                    ]

                    m.next = "CHECK_PACKET"

            # CHECK_PACKET -- we've now received our full packet; we'll check it for validity.
            with m.State("CHECK_PACKET"):

                # A minor error occurs if if one of our CRCs mismatches; in which case the link can
                # continue after sending an LBAD link command. [USB3.2r1: 7.2.4.1.5].
                # We'll strobe our less-severe "bad packet" indicator, but still reject the header.
                crc5_failed  = (expected_crc5 != packet.crc5)
                crc16_failed = (crc16.crc     != packet.crc16)
                with m.If(crc5_failed | crc16_failed):
                    m.d.comb += self.bad_packet.eq(1)

                # Our worst-case scenario is we're receiving a packet with an unexpected sequence
                # number; this indicates that we've lost sequence, and our device should move back to
                # into Recovery [USB3.2r1: 7.2.4.1.5].
                with m.Elif(packet.sequence_number != self.expected_sequence):
                    m.d.comb += self.bad_sequence.eq(1)

                # If neither of the above checks failed, we now know we have a valid header packet!
                # We'll output our packet, and then return to IDLE.
                with m.Else():
                    m.d.ss += [
                        self.new_packet  .eq(1),
                        self.packet      .eq(packet)
                    ]

                m.next = "WAIT_FOR_HPSTART"


        return m


class RawHeaderPacketReceiverTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = RawHeaderPacketReceiver

    def initialize_signals(self):
        yield self.dut.sink.valid.eq(1)

    def provide_data(self, *tuples):
        """ Provides the receiver with a sequence of (data, ctrl) values. """

        # Provide each word of our data to our receiver...
        for data, ctrl in tuples:
            yield self.dut.sink.data.eq(data)
            yield self.dut.sink.ctrl.eq(ctrl)
            yield


    @ss_domain_test_case
    def test_good_packet_receive(self):
        dut  = self.dut

        # Data input for an actual Link Management packet (seq #0).
        yield from self.provide_data(
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0x00000280, 0b0000),
            (0x00010004, 0b0000),
            (0x00000000, 0b0000),
            (0x10001845, 0b0000),
        )

        # ... after a cycle to process, we should see an indication that the packet is good.
        yield from self.advance_cycles(2)
        self.assertEqual((yield dut.new_packet),   1)
        self.assertEqual((yield dut.bad_packet),   0)
        self.assertEqual((yield dut.bad_sequence), 0)


    @ss_domain_test_case
    def test_bad_sequence_receive(self):
        dut  = self.dut

        # Expect a sequence number other than the one we'll be providing.
        yield dut.expected_sequence.eq(3)

        # Data input for an actual Link Management packet (seq #0).
        yield from self.provide_data(
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0x00000280, 0b0000),
            (0x00010004, 0b0000),
            (0x00000000, 0b0000),
            (0x10001845, 0b0000),
        )

        # ... after a cycle to process, we should see an indication that the packet is good.
        yield from self.advance_cycles(1)
        self.assertEqual((yield dut.new_packet),   0)
        self.assertEqual((yield dut.bad_packet),   0)
        self.assertEqual((yield dut.bad_sequence), 1)



    @ss_domain_test_case
    def test_bad_packet_receive(self):
        dut  = self.dut

        # Data input for an actual Link Management packet (seq #0),
        # but with the last word corrupted to invalidate our CRC16.
        yield from self.provide_data(
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0x00000280, 0b0000),
            (0x00010004, 0b0000),
            (0xFFFFFFFF, 0b0000),
            (0x10001845, 0b0000),
        )

        # ... after a cycle to process, we should see an indication that the packet is bad.
        yield from self.advance_cycles(1)
        self.assertEqual((yield dut.new_packet),   0)
        self.assertEqual((yield dut.bad_packet),   1)
        self.assertEqual((yield dut.bad_sequence), 0)


    @ss_domain_test_case
    def test_bad_crc_and_sequence_receive(self):
        dut  = self.dut

        # Completely invalid link packet, guaranteed to have a bad sequence number & CRC.
        yield from self.provide_data(
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0xFFFFFFFF, 0b0000),
            (0xFFFFFFFF, 0b0000),
            (0xFFFFFFFF, 0b0000),
            (0xFFFFFFFF, 0b0000),
        )

        # Once we've processed this, we should see that there's a bad packet; but that it's
        # corrupted enough that our sequence no longer matters.
        yield from self.advance_cycles(1)
        self.assertEqual((yield dut.new_packet),   0)
        self.assertEqual((yield dut.bad_packet),   1)
        self.assertEqual((yield dut.bad_sequence), 0)


class HeaderPacketReceiver(Elaboratable):
    """ Receiver-side Header Packet logic.

    This module handles all header-packet-reception related logic for the link layer; including
    header packet reception, buffering, flow control (credit management), and link command transmission.

    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input stream [monitor only]
        Stream that carries data from the physical layer, to be monitored.
    source: USBRawSuperSpeedStream(), output stream
        Stream that carries link commands from this unit down down to the physical layer.

    enable: Signal(), input
        When asserted, this unit will be enabled; and will be allowed to start
        transmitting link commands. Asserting this signal after a reset will perform
        a header sequence and link credit advertisement.
    usb_reset: Signal(), input
        Strobe; can be asserted to indicate that a USB reset has occurred, and sequencing
        should be restarted.

    queue: HeaderQueue(), output stream
        Stream carrying any header packets to be transmitted.

    retry_received: Signal(), input
        Strobe; should be asserted when the transmitter has seen a RETRY handshake.
    retry_required: Signal(), output
        Strobe; pulsed to indicate that we should send a RETRY handshake.

    link_command_sent: Signal(), output
        Strobe; pulses each time a link command is completed.
    keepalive_required: Signal(), input
        Strobe; when asserted; a keepalive packet will be generated.
    packet_received: Signal(), output
        Strobe; pulsed when an event occurs that should reset the USB3 "packet received" timers.
        This does *not* indicate valid data is present on the output :attr:``queue``; this has its
        own valid signal.
    bad_packet_received: Signal(), output
        Strobe; pulsed when a receive error occurs. For error counting at the link level.

    accept_power_state: Signal(), input
        Strobe; when pulsed, a LAU (Link-state acceptance) will be generated.
    reject_power_state: Signal(), input
        Strobe; when pulsed, a LXU (Link-state rejection) will be generated.
    acknowledge_power_state: Signal(), input
        Strobe; when pulsed, a LPMA (Link-state acknowledgement) will be generated.
    """

    SEQUENCE_NUMBER_WIDTH = 3

    def __init__(self, *, buffer_count=4, downstream_facing=False):
        self._buffer_count = buffer_count
        self._is_downstream_facing = downstream_facing

        #
        # I/O port
        #
        self.sink                    = USBRawSuperSpeedStream()
        self.source                  = USBRawSuperSpeedStream()

        # Simple controls.
        self.enable                  = Signal()
        self.usb_reset               = Signal()

        # Header Packet Queue
        self.queue                   = HeaderQueue()

        # Event signaling.
        self.retry_received          = Signal()
        self.lrty_pending            = Signal()
        self.retry_required          = Signal()
        self.recovery_required       = Signal()

        self.link_command_sent       = Signal()
        self.keepalive_required      = Signal()
        self.packet_received         = Signal()
        self.bad_packet_received     = Signal()

        self.accept_power_state      = Signal()
        self.reject_power_state      = Signal()
        self.acknowledge_power_state = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Sequence tracking.
        #

        # Keep track of which sequence number we expect to see.
        expected_sequence_number = Signal(self.SEQUENCE_NUMBER_WIDTH)

        # Keep track of which credit we'll need to issue next...
        next_credit_to_issue     = Signal(range(self._buffer_count))

        # ... and which header we'll need to ACK next.
        # We'll start with the maximum number, so our first advertisement wraps us back around to zero.
        next_header_to_ack       = Signal.like(expected_sequence_number, reset=-1)


        #
        # Task "queues".
        #

        # Keep track of how many header received acknowledgements (LGOODs) we need to send.
        acks_to_send      = Signal(range(self._buffer_count + 1), reset=1)
        enqueue_ack       = Signal()
        dequeue_ack       = Signal()

        with m.If(enqueue_ack & ~dequeue_ack):
            m.d.ss += acks_to_send.eq(acks_to_send + 1)
        with m.If(dequeue_ack & ~enqueue_ack):
            m.d.ss += acks_to_send.eq(acks_to_send - 1)


        # Keep track of how many link credits we've yet to free.
        # We'll start with every one of our buffers marked as "pending free"; this ensures
        # we perform our credit restoration properly.
        credits_to_issue  = Signal.like(acks_to_send, reset=self._buffer_count)
        enqueue_credit_issue = Signal()
        dequeue_credit_issue = Signal()

        with m.If(enqueue_credit_issue & ~dequeue_credit_issue):
            m.d.ss += credits_to_issue.eq(credits_to_issue + 1)
        with m.If(dequeue_credit_issue & ~enqueue_credit_issue):
            m.d.ss += credits_to_issue.eq(credits_to_issue - 1)

        # Keep track of whether we should be sending an LBAD.
        lbad_pending = Signal()

        # Keep track of whether a retry has been requested.
        lrty_pending = self.lrty_pending
        with m.If(self.retry_required):
            m.d.ss += lrty_pending.eq(1)

        # Keep track of whether a keepalive has been requested.
        keepalive_pending = Signal()
        with m.If(self.keepalive_required):
            m.d.ss += keepalive_pending.eq(1)

        # Keep track of whether we're expected to send an power state response.
        lau_pending  = Signal()
        lxu_pending  = Signal()
        lpma_pending = Signal()

        with m.If(self.accept_power_state):
            m.d.ss += lau_pending.eq(1)
        with m.If(self.reject_power_state):
            m.d.ss += lxu_pending.eq(1)
        with m.If(self.acknowledge_power_state):
            m.d.ss += lpma_pending.eq(1)


        #
        # Header Packet Buffers
        #

        # Track which buffer will be filled next.
        read_pointer      = Signal(range(self._buffer_count))
        write_pointer     = Signal.like(read_pointer)

        # Track how many buffers we currently have in use.
        buffers_filled    = Signal.like(credits_to_issue, reset=0)
        reserve_buffer    = Signal()
        release_buffer    = Signal()

        with m.If(reserve_buffer & ~release_buffer):
            m.d.ss += buffers_filled.eq(buffers_filled + 1)
        with m.If(release_buffer & ~reserve_buffer):
            m.d.ss += buffers_filled.eq(buffers_filled - 1)

        # Create buffers to receive any incoming header packets.
        buffers = Array(HeaderPacket() for _ in range(self._buffer_count))


        #
        # Packet reception (physical layer -> link layer).
        #

        # Flag that determines when we should ignore packets.
        #
        # After a receive error, we'll want to ignore all packets until we see a "retry"
        # link command; so we don't receive packets out of order.
        ignore_packets = Signal()

        # Create our raw packet parser / receiver.
        m.submodules.receiver = rx = RawHeaderPacketReceiver()
        m.d.comb += [
            # Our receiver passively monitors the data received for header packets.
            rx.sink                   .tap(self.sink),

            # Ensure it's always up to date about what sequence numbers we expect.
            rx.expected_sequence      .eq(expected_sequence_number),

            # If we ever get a bad header packet sequence, we're required to retrain
            # the link [USB3.2r1: 7.2.4.1.5]. Pass the event through directly.
            self.recovery_required    .eq(rx.bad_sequence & ~ignore_packets),

            # Notify the link layer when packets are received, for keeping track of our timers.
            self.packet_received      .eq(rx.new_packet),

            # Notify the link layer if any bad packets are received; for diagnostics.
            self.bad_packet_received  .eq(rx.bad_packet)
        ]


        # If we receive a valid packet, it's time for us to buffer it!
        with m.If(rx.new_packet & ~ignore_packets):
            m.d.ss += [
                # Load our header packet into the next write buffer...
                buffers[write_pointer]    .eq(rx.packet),

                # ... advance to the next buffer and sequence number...
                write_pointer             .eq(write_pointer + 1),
                expected_sequence_number  .eq(expected_sequence_number + 1),
            ]
            m.d.comb += [
                # ... mark the buffer space as occupied by valid data ...
                reserve_buffer            .eq(1),

                # ... and queue an ACK for this packet.
                enqueue_ack               .eq(1)
            ]


        # If we receive a bad packet, we'll need to request that the other side re-send.
        # The rules for this are summarized in [USB3.2r1: 7.2.4.1.5], and in comments below.
        with m.If(rx.bad_packet & ~ignore_packets):


            m.d.ss += [
                # First, we'll need to schedule transmission of an LBAD, which notifies the other
                # side that we received a bad packet; and that it'll need to transmit all unack'd
                # header packets to us again.
                lbad_pending    .eq(1),

                # Next, we'll need to make sure we don't receive packets out of sequence. This means
                # we'll have to start ignoring packets until the other side responds to the LBAD.
                # The other side respond with an Retry link command (LRTY) once it's safe for us to
                # pay attention to packets again.
                ignore_packets  .eq(1)
            ]


        # Finally, if we receive a Retry link command, this means we no longer need to ignore packets.
        # This typically happens in response to us sending an LBAD and marking future packets as ignored.
        with m.If(self.retry_received):
            m.d.ss += ignore_packets.eq(0)


        #
        # Packet delivery (link layer -> physical layer).
        #
        m.d.comb += [
            # As long as we have at least one buffer filled, we have header packets pending.
            self.queue.valid    .eq(buffers_filled > 0),

            # Always provide the value of our oldest packet out to our consumer.
            self.queue.header    .eq(buffers[read_pointer])
        ]


        # If the protocol layer is marking one of our packets as consumed, we no longer
        # need to buffer it -- it's the protocol layer's problem, now!
        with m.If(self.queue.valid & self.queue.ready):

            # Move on to reading from the next buffer in sequence.
            m.d.ss += read_pointer.eq(read_pointer + 1)

            m.d.comb += [
                # First, we'll free the buffer associated with the relevant packet...
                release_buffer        .eq(1),

                # ... and request that our link partner be notified of the new space.
                enqueue_credit_issue  .eq(1)
            ]


        #
        # Link command generation.
        #
        m.submodules.lc_generator = lc_generator = LinkCommandGenerator()
        m.d.comb += [
            self.source             .stream_eq(lc_generator.source),
            self.link_command_sent  .eq(lc_generator.done),
        ]


        with m.FSM(domain="ss"):

            # DISPATCH_COMMAND -- the state in which we identify any pending link commands necessary,
            # and then move to the state in which we'll send them.
            with m.State("DISPATCH_COMMAND"):

                with m.If(self.enable):
                    # NOTE: the order below is important; changing it can easily break things:
                    # - ACKS must come before credits, as we must send an LGOOD before we send our initial credits.
                    # - LBAD must come after ACKs and credit management, as all scheduled ACKs need to be
                    #   sent to the other side for the LBAD to have the correct semantic meaning.

                    with m.If(lrty_pending):
                        m.next = "SEND_LRTY"

                    # If we have acknowledgements to send, send them.
                    with m.Elif(acks_to_send):
                        m.next = "SEND_ACKS"

                    # If we have link credits to issue, move to issuing them to the other side.
                    with m.Elif(credits_to_issue):
                        m.next = "ISSUE_CREDITS"

                    # If we need to send an LBAD, do so.
                    with m.Elif(lbad_pending):
                        m.next = "SEND_LBAD"

                    # If we need to send a link power-state command, do so.
                    with m.Elif(lxu_pending):
                        m.next = "SEND_LXU"

                    # If we need to send a keepalive, do so.
                    with m.Elif(keepalive_pending):
                        m.next = "SEND_KEEPALIVE"



                # Once we've become disabled, we'll want to prepare for our next enable.
                # This means preparing for our advertisement, by:
                with m.If(Fell(self.enable) | self.usb_reset):
                    m.d.ss += [
                        # -Resetting our pending ACKs to 1, so we perform an sequence number advertisement
                        #  when we're next enabled.
                        acks_to_send          .eq(1),

                        # -Decreasing our next sequence number; so we maintain a continuity of sequence numbers
                        #  without counting the advertising one. This doesn't seem to be be strictly necessary
                        #  per the spec; but seem to make analyzers happier, so we'll go with it.
                        next_header_to_ack    .eq(next_header_to_ack - 1),

                        # - Clearing all of our buffers.
                        read_pointer          .eq(0),
                        write_pointer         .eq(0),
                        buffers_filled        .eq(0),

                        # - Preparing to re-issue all of our buffer credits.
                        next_credit_to_issue  .eq(0),
                        credits_to_issue      .eq(self._buffer_count),

                        # - Clear our pending events.
                        lrty_pending          .eq(0),
                        lbad_pending          .eq(0),
                        keepalive_pending     .eq(0),
                        ignore_packets        .eq(0)
                    ]

                    # If this is a USB Reset, also reset our sequences.
                    with m.If(self.usb_reset):
                        m.d.ss += [
                            expected_sequence_number  .eq(0),
                            next_header_to_ack        .eq(-1)
                        ]


            # SEND_ACKS -- a valid header packet has been received, or we're advertising
            # our initial sequence number; send an LGOOD packet.
            with m.State("SEND_ACKS"):

                # Send an LGOOD command, acknowledging the last received packet header.
                m.d.comb += [
                    lc_generator.generate      .eq(1),
                    lc_generator.command       .eq(LinkCommand.LGOOD),
                    lc_generator.subtype       .eq(next_header_to_ack)
                ]

                # Wait until our link command is done, and then move on.
                with m.If(lc_generator.done):
                    # Move to the next header packet in the sequence, and decrease
                    # the number of outstanding ACKs.
                    m.d.comb += dequeue_ack         .eq(1)
                    m.d.ss   += next_header_to_ack  .eq(next_header_to_ack + 1)

                    # If this was the last ACK we had to send, move back to our dispatch state.
                    with m.If(acks_to_send == 1):
                        m.next = "DISPATCH_COMMAND"


            # ISSUE_CREDITS -- header packet buffers have been freed; and we now need to notify the
            # other side, so it knows we have buffers available.
            with m.State("ISSUE_CREDITS"):

                # Send an LCRD command, indicating that we have a free buffer.
                m.d.comb += [
                    lc_generator.generate      .eq(1),
                    lc_generator.command       .eq(LinkCommand.LCRD),
                    lc_generator.subtype       .eq(next_credit_to_issue)
                ]

                # Wait until our link command is done, and then move on.
                with m.If(lc_generator.done):
                    # Move to the next credit...
                    m.d.comb += dequeue_credit_issue  .eq(1)
                    m.d.ss   += next_credit_to_issue  .eq(next_credit_to_issue + 1)

                    # If this was the last credit we had to issue, move back to our dispatch state.
                    with m.If(credits_to_issue == 1):
                        m.next = "DISPATCH_COMMAND"


            # SEND_LBAD -- we've received a bad header packet; we'll need to let the other side know.
            with m.State("SEND_LBAD"):
                m.d.comb += [
                    lc_generator.generate      .eq(1),
                    lc_generator.command       .eq(LinkCommand.LBAD),
                ]

                # Once we've sent the LBAD, we can mark is as no longer pending and return to our dispatch.
                # (We can't ever have multiple LBADs queued up; as we ignore future packets after sending one.)
                with m.If(lc_generator.done):
                    m.d.ss += lbad_pending.eq(0)
                    m.next = "DISPATCH_COMMAND"


            # SEND_LRTY -- our transmitter has requested that we send an retry indication to the other side.
            # We'll do our transmitter a favor and do so.
            with m.State("SEND_LRTY"):
                m.d.comb += [
                    lc_generator.generate      .eq(1),
                    lc_generator.command       .eq(LinkCommand.LRTY)
                ]

                with m.If(lc_generator.done):
                    m.d.ss += lrty_pending.eq(0)
                    m.next = "DISPATCH_COMMAND"



            # SEND_KEEPALIVE -- our link layer timer has requested that we send a keep-alive,
            # indicating that we're still in U0 and the link is still good. Do so.
            with m.State("SEND_KEEPALIVE"):

                # Send the correct packet type for the direction our port is facing.
                command = LinkCommand.LDN if self._is_downstream_facing else LinkCommand.LUP

                m.d.comb += [
                    lc_generator.generate      .eq(1),
                    lc_generator.command       .eq(command)
                ]

                # Once we've send the keepalive, we can mark is as no longer pending and return to our dispatch.
                # (There's no sense in sending repeated keepalives; one gets the message across.)
                with m.If(lc_generator.done):
                    m.d.ss += keepalive_pending.eq(0)
                    m.next = "DISPATCH_COMMAND"


            # SEND_LXU -- we're being instructed to reject a requested power-state transfer.
            # We'll send an LXU packet to inform the other side of the rejection.
            with m.State("SEND_LXU"):
                m.d.comb += [
                    lc_generator.generate      .eq(1),
                    lc_generator.command       .eq(LinkCommand.LXU)
                ]

                with m.If(lc_generator.done):
                    m.d.ss += lxu_pending.eq(0)
                    m.next = "DISPATCH_COMMAND"

        return m


if __name__ == "__main__":
    unittest.main()
