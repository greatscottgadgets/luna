#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test    import LunaSSGatewareTestCase, ss_domain_test_case

from luna.gateware.usb.usb3.link.data import DataPacketReceiver

class DataPacketReceiverTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = DataPacketReceiver

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
    def test_unaligned_1B_packet_receive(self):

        # Provide a packet pair to the device.
        # (This data is from an actual recorded data packet.)
        yield from self.provide_data(
            # Header packet.
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0x32000008, 0b0000),
            (0x00010000, 0b0000),
            (0x08000000, 0b0000),
            (0xE801A822, 0b0000),

            # Payload packet.
            (0xF75C5C5C, 0b1111),
            (0x000000FF, 0b0000),
            (0xFDFDFDFF, 0b1110),
        )

        self.assertEqual((yield self.dut.packet_good), 1)


    @ss_domain_test_case
    def test_unaligned_2B_packet_receive(self):

        # Provide a packet pair to the device.
        # (This data is from an actual recorded data packet.)
        yield from self.provide_data(
            # Header packet.
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0x34000008, 0b0000),
            (0x00020000, 0b0000),
            (0x08000000, 0b0000),
            (0xD005A242, 0b0000),

            # Payload packet.
            (0xF75C5C5C, 0b1111),
            (0x2C98BBAA, 0b0000),
            (0xFDFD4982, 0b1110),
        )

        self.assertEqual((yield self.dut.packet_good), 1)



    @ss_domain_test_case
    def test_aligned_packet_receive(self):

        # Provide a packet pair to the device.
        # (This data is from an actual recorded data packet.)
        yield from self.provide_data(
            # Header packet.
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0x00000008, 0b0000),
            (0x00088000, 0b0000),
            (0x08000000, 0b0000),
            (0xA8023E0F, 0b0000),

            # Payload packet.
            (0xF75C5C5C, 0b1111),
            (0x001E0500, 0b0000),
            (0x00000000, 0b0000),
            (0x0EC69325, 0b0000),
        )

        self.assertEqual((yield self.dut.packet_good), 1)

