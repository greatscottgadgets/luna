#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Incomplete example for working with a hardware PIPE PHY."""

from amaranth import *

from luna                          import top_level_cli
from luna.gateware.platform        import NullPin
from luna.gateware.usb.devices.ila import USBIntegratedLogicAnalyzer, USBIntegratedLogicAnalyzerFrontend

from luna.gateware.interface.serdes_phy.backends.ecp5 import LunaECP5SerDes
from luna.gateware.interface.serdes_phy.phy           import SerDesPHY

class PIPEPhyExample(Elaboratable):
    """ Hardware module that demonstrates grabbing a PHY resource with gearing. """

    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our core PIPE PHY. Since PHY configuration is per-board, we'll just ask
        # our platform for a pre-configured USB3 PHY.
        m.submodules.phy = phy = platform.create_usb3_phy()

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    top_level_cli(PIPEPhyExample)
