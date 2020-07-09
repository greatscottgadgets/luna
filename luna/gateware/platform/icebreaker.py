#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" iCEBreaker Platform definitions.

This platform does not have an explicit USB port. Instead, you'll need to connect a USB breakout.

This is an -unsupported- platform! To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.icebreaker:IceBreakerPlatform"

This board is not routinely tested, and performance is not guaranteed.
"""

import os
import logging
import subprocess


from nmigen import Elaboratable, ClockDomain, Module, ClockSignal, Instance, Signal, Const
from nmigen.build import Resource, Subsignal, Pins, Attrs, Clock, Connector, PinsN
from nmigen.vendor.lattice_ice40 import LatticeICE40Platform

from .core import LUNAPlatform


class IceBreakerDomainGenerator(Elaboratable):
    """ Stub clock domain generator; stands in for the typical LUNA one.

    This generator creates domains; but currently does not configure them.
    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains...
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        # ... ensure our clock is never instantiated with a Global buffer.
        platform.lookup(platform.default_clk).attrs['GLOBAL'] = False

        # ... create our 48 MHz IO and 12 MHz USB clock...
        m.submodules.pll = Instance("SB_PLL40_2F_PAD",
            i_PACKAGEPIN    = platform.request(platform.default_clk, dir="i"),
            i_RESETB        = Const(1),
            i_BYPASS        = Const(0),

            o_PLLOUTGLOBALA   = ClockSignal("sync"),
            o_PLLOUTGLOBALB   = ClockSignal("usb"),

            # Create a 48 MHz PLL clock...
            p_FEEDBACK_PATH = "SIMPLE",
            p_PLLOUT_SELECT_PORTA = "GENCLK",
            p_PLLOUT_SELECT_PORTB = "SHIFTREG_0deg",
            p_DIVR          = 0,
            p_DIVF          = 63,
            p_DIVQ          = 4,
            p_FILTER_RANGE  = 1,
        )

        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync"))
        ]

        return m


class IceBreakerPlatform(LatticeICE40Platform, LUNAPlatform):
    """ Base class for Fomu platforms. """

    device      = "iCE40UP5K"
    package     = "SG48"
    name        = "iCEBreaker"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = IceBreakerDomainGenerator

    # We only have a direct connection on our USB lines, so use that for USB comms.
    default_usb_connection = "tnt_usb"

    default_clk = "clk12"
    resources   = [
        Resource("clk12", 0, Pins("35", dir="i"),
                 Clock(12e6), Attrs(GLOBAL=True, IO_STANDARD="SB_LVCMOS")),

        Resource("led",   0, PinsN("11", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led",   1, PinsN("37", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),

        # Semantic aliases
        Resource("led_r", 0, PinsN("11", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 0, PinsN("37", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),

        # Default USB position.
        Resource("tnt_usb", 0,
            Subsignal("d_p",    Pins("31")),
            Subsignal("d_n",    Pins("34")),
            Subsignal("pullup", Pins("38", dir="o")),
            Attrs(IO_STANDARD="SB_LVCMOS"),
        ),

        Resource("kbeckmann_usb", 0,
            Subsignal("d_p",    Pins("43")),
            Subsignal("d_n",    Pins("38")),
            Subsignal("pullup", Pins("34", dir="o")),
            Attrs(IO_STANDARD="SB_LVCMOS"),
        ),

        # Compatibility aliases.
        Resource("user_io", 0, PinsN("4", dir="io"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("user_io", 1, PinsN("2", dir="io"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("user_io", 2, PinsN("47", dir="io"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("user_io", 3, PinsN("25", dir="io"), Attrs(IO_STANDARD="SB_LVCMOS")),

    ]
    connectors = [
        Connector("pmod", 0, " 4  2 47 45 - -  3 48 46 44 - -"), # PMOD1A
        Connector("pmod", 1, "43 38 34 31 - - 42 36 32 28 - -"), # PMOD1B
        Connector("pmod", 2, "27 25 21 19 - - 26 23 20 18 - -"), # PMOD2
    ]

    def __init__(self, *args, **kwargs):
        logging.warning("This platform is not officially supported, and thus not tested. Your results may vary.")
        logging.warning("Note also that this platform does not use the iCEBreaker's main USB port!")
        logging.warning("You'll need to connect a cable or pmod. See the platform file for more info.")
        super().__init__(*args, **kwargs)

    def toolchain_program(self, products, name):
        iceprog = os.environ.get("ICEPROG", "iceprog")
        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call([iceprog, bitstream_filename])

    def toolchain_flash(self, products, name="top"):
        self.toolchain_program(products, name)
