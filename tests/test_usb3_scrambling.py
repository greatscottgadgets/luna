#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test import LunaSSGatewareTestCase, ss_domain_test_case

from luna.gateware.usb.usb3.physical.scrambling import ScramblerLFSR

class ScramblerLFSRTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = ScramblerLFSR

    @ss_domain_test_case
    def test_lfsr_stream(self):
        # From the table of 8-bit encoded values, [USB3.2, Appendix B.1].
        # We can continue this as long as we want to get more thorough testing,
        # but for now, this is probably enough.
        scrambled_sequence = [
            0x14c017ff, 0x8202e7b2, 0xa6286e72, 0x8dbf6dbe,   # Row 1 (0x00)
            0xe6a740be, 0xb2e2d32c, 0x2a770207, 0xe0be34cd,   # Row 2 (0x10)
            0xb1245da7, 0x22bda19b, 0xd31d45d4, 0xee76ead7    # Row 3 (0x20)
        ]

        yield self.dut.advance.eq(1)
        yield

        # Check that our LFSR produces each of our values in order.
        for index, value in enumerate(scrambled_sequence):
            self.assertEqual((yield self.dut.value), value, f"incorrect value at cycle {index}")
            yield

