#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Incomplete example for working the SerDes-based a PIPE PHY. """

from nmigen import *

from luna                          import top_level_cli
from luna.gateware.platform        import NullPin

from luna.usb3            import USBSuperSpeedDevice


class USBSuperSpeedExample(Elaboratable):
    """ Work-in-progress example/test fixture for a SuperSpeed device. """


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our core PIPE PHY. Since PHY configuration is per-board, we'll just ask
        # our platform for a pre-configured USB3 PHY.
        m.submodules.phy = phy = platform.create_usb3_phy()

        # Create our core SuperSpeed device.
        m.submodules.usb = USBSuperSpeedDevice(phy=phy)

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    top_level_cli(USBSuperSpeedExample)
