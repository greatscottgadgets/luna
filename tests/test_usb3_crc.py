#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test              import LunaSSGatewareTestCase, ss_domain_test_case

from luna.gateware.usb.usb3.link.crc import DataPacketPayloadCRC

class DataPacketPayloadCRCTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = DataPacketPayloadCRC

    @ss_domain_test_case
    def test_aligned_crc(self):
        dut = self.dut

        #yield dut.advance_word.eq(1)

        for i in (0x02000112, 0x40000000):
            yield dut.data_input.eq(i)
            yield from self.pulse(dut.advance_word, step_after=False)

        self.assertEqual((yield dut.crc), 0x34984B13)


    @ss_domain_test_case
    def test_unaligned_crc(self):
        dut = self.dut


        # Aligned section of a real USB data capture, from a USB flash drive.
        aligned_section =[
            0x03000112,
            0x09000000,
            0x520013FE,
            0x02010100,
        ]

        # Present the aligned section...
        for i in aligned_section:
            yield dut.data_input.eq(i)
            yield from self.pulse(dut.advance_word, step_after=False)

        # ... and then our unaligned data.
        yield dut.data_input.eq(0x0000_0103)
        yield

        # Our next-CRC should indicate the correct value...
        self.assertEqual((yield dut.next_crc_2B), 0x540aa487)

        # ...and after advancing, we should see the same value on our CRC output.
        yield from self.pulse(dut.advance_2B)
        self.assertEqual((yield dut.crc), 0x540aa487)
