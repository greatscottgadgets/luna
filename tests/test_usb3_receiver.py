#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test                   import LunaSSGatewareTestCase, ss_domain_test_case

from luna.gateware.usb.usb3.link.receiver import RawHeaderPacketReceiver

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
