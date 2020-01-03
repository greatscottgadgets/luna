#
# This file is part of LUNA.
#

import sys

from nmigen import Signal, Module, Elaboratable, ClockDomain, ClockSignal, Cat
from luna.gateware.platform.luna_r0_1 import LUNAPlatformR01

from nmigen.back import verilog


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

    if len(sys.argv) == 2:
        build_only = (sys.argv[1] == 'build')
    else:
        build_only = False

    platform = LUNAPlatformR01()
    platform.build(Blinky(), do_program=not build_only)
