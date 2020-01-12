#!/usr/bin/env python3
#
# This file is part of LUNA.
#

import sys

from nmigen import Signal, Module, Elaboratable, ClockDomain, ClockSignal, Cat

from luna import top_level_cli
from luna.gateware.platform.luna_r0_1 import LUNAPlatformR01

class Blinky(Elaboratable):
    """ Hardware module that validates basic LUNA functionality. """


    def elaborate(self, platform):
        """ Generate the Binky tester. """

        m = Module()

        # Grab our I/O connectors.
        leds    = [platform.request("led", i, dir="o") for i in range(0, 6)]
        user_io = [platform.request("user_io", i, dir="o") for i in range(0, 4)]

        # Clock divider / counter.
        counter = Signal(28)
        m.d.sync += counter.eq(counter + 1)

        # Attach the LEDs and User I/O to the MSBs of our counter.
        m.d.comb += Cat(leds).eq(counter[-7:-1])
        m.d.comb += Cat(user_io).eq(counter[7:21])

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    top_level_cli(Blinky)
