#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Header Packet processing / buffering gateware. """

import unittest

from nmigen            import *

from ..physical.coding import SHP, EPF, stream_matches_symbols
from .crc              import compute_usb_crc5, HeaderPacketCRC
from ...stream         import USBRawSuperSpeedStream

from ....test.utils    import LunaSSGatewareTestCase, ss_domain_test_case


class HeaderPacket(Record):
    """ Container that represents a Header Packet. """

    def __init__(self):
        super().__init__([

            # TODO: expand these, if we use this up at the protocol level?
            ('dw0',             32),
            ('dw1',             32),
            ('dw2',             32),

            # Our final data word contains the link-layer fields.
            ('crc16',           16),
            ('sequence_number',  3),
            ('dw3_reserved',     3),
            ('hub_depth',        3),
            ('deferred',         1),
            ('delayed',          1),
            ('crc5',             5),
        ])


class HeaderPacketReceiver(Elaboratable):
    """ Class that monitors the USB bus for Header Packets, and receives them.

    This class performs the validations required at the link layer of the USB specification;
    which include checking the CRC-5 and CRC-16 embedded within the header packet.


    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input stream
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
                        packet.deferred         .eq(sink.data[25]),
                        packet.delayed          .eq(sink.data[26]),
                        packet.crc5             .eq(sink.data[27:32]),

                        # ... and pipeline a CRC of the to the link control word.
                        expected_crc5           .eq(compute_usb_crc5(sink.data[16:27]))
                    ]

                    m.next = "CHECK_PACKET"

            # CHECK_PACKET -- we've now received our full packet; we'll check it for validity.
            with m.State("CHECK_PACKET"):

                # Our worst-case scenario is we're receiving a packet with an unexpected sequence
                # number; this indicates that we've lost sequence, and our device should move back to
                # into Recovery [USB3.2r1: 7.2.4.1.5].
                with m.If(packet.sequence_number != self.expected_sequence):
                    m.d.comb += self.bad_sequence.eq(1)

                # A less-worse case is if one of our CRCs mismatches; in which case the link can
                # continue after sending an LBAD link command. [USB3.2r1: 7.2.4.1.5].
                # We'll strobe our less-severe "bad packet" indicator, but still reject the header.
                crc5_failed  = (expected_crc5 != packet.crc5)
                crc16_failed = (crc16.crc     != packet.crc16)
                with m.Elif(crc5_failed | crc16_failed):
                    m.d.comb += self.bad_packet.eq(1)

                # If neither of the above checks failed, we now know we have a valid header packet!
                # We'll output our packet, and then return to IDLE.
                with m.Else():
                    m.d.ss += [
                        self.new_packet  .eq(1),
                        self.packet      .eq(packet)
                    ]

                m.next = "WAIT_FOR_HPSTART"


        return m


class HeaderPacketReceiverTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = HeaderPacketReceiver

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
    def test_bad_sequence_receive(self):
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

        # Once we've processed this, we should see that there's a bad sequence; which should
        # trump our bad packet indicator, and prevent that from going high.
        yield from self.advance_cycles(1)
        self.assertEqual((yield dut.new_packet),   0)
        self.assertEqual((yield dut.bad_packet),   0)
        self.assertEqual((yield dut.bad_sequence), 1)


if __name__ == "__main__":
    unittest.main()
