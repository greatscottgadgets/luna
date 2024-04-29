#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test import LunaGatewareTestCase, sync_test_case

from luna.gateware.architecture.car import PHYResetController

class PHYResetControllerTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = PHYResetController

    def initialize_signals(self):
        yield self.dut.trigger.eq(0)

    @sync_test_case
    def test_power_on_reset(self):

        #
        # After power-on, the PHY should remain in reset for a while.
        #
        yield
        self.assertEqual((yield self.dut.phy_reset), 1)

        yield from self.advance_cycles(30)
        self.assertEqual((yield self.dut.phy_reset), 1)

        yield from self.advance_cycles(60)
        self.assertEqual((yield self.dut.phy_reset), 1)

        #
        # Then, after the relevant reset time, it should resume being unasserted.
        #
        yield from self.advance_cycles(31)
        self.assertEqual((yield self.dut.phy_reset), 0)
        self.assertEqual((yield self.dut.phy_stop),  1)

        yield from self.advance_cycles(120)
        self.assertEqual((yield self.dut.phy_stop),  0)
