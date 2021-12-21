#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" iCEBreaker Platform definitions.

The iCEBreaker Bitsy is a non-core board. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.icebreaker:IceBreakerBitsyPlatform"

The full size iCEBreaker does not have an explicit USB port. Instead, you'll need to connect a USB breakout.
The full iCEBreaker is an -unsupported- platform! To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.icebreaker:IceBreakerPlatform"
"""

import os
import logging
import subprocess


from amaranth import *
from amaranth.build import *
from amaranth.vendor.lattice_ice40 import LatticeICE40Platform

from amaranth_boards.resources import *
from amaranth_boards.icebreaker import ICEBreakerPlatform as _IceBreakerPlatform
from amaranth_boards.icebreaker_bitsy import ICEBreakerBitsyPlatform as _IceBreakerBitsyPlatform

from .core import LUNAPlatform


class IceBreakerDomainGenerator(Elaboratable):
    """ Creates clock domains for the iCEBreaker. """

    def elaborate(self, platform):
        m = Module()

        # Create our domains...
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        # ... ensure our clock is never instantiated with a Global buffer.
        platform.lookup(platform.default_clk).attrs['GLOBAL'] = False

        # ... create our 48 MHz IO and 12 MHz USB clocks...
        clk48 = Signal()
        clk12 = Signal()
        m.submodules.pll = Instance("SB_PLL40_2F_PAD",
            i_PACKAGEPIN    = platform.request(platform.default_clk, dir="i"),
            i_RESETB        = Const(1),
            i_BYPASS        = Const(0),

            o_PLLOUTGLOBALA   = clk48,
            o_PLLOUTGLOBALB   = clk12,

            # Create a 48 MHz PLL clock...
            p_FEEDBACK_PATH = "SIMPLE",
            p_PLLOUT_SELECT_PORTA = "GENCLK",
            p_PLLOUT_SELECT_PORTB = "SHIFTREG_0deg",
            p_DIVR          = 0,
            p_DIVF          = 63,
            p_DIVQ          = 4,
            p_FILTER_RANGE  = 1,
        )

        # ... and constrain them to their new frequencies.
        platform.add_clock_constraint(clk48, 48e6)
        platform.add_clock_constraint(clk12, 12e6)


        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(clk48),
            ClockSignal("fast")    .eq(clk48),
            ClockSignal("sync")    .eq(clk48),
            ClockSignal("usb")     .eq(clk12)
        ]


        return m


class IceBreakerPlatform(_IceBreakerPlatform, LUNAPlatform):
    name                   = "iCEBreaker"
    clock_domain_generator = IceBreakerDomainGenerator
    default_usb_connection = "usb_pmod_1a"

    additional_resources   = [
        # iCEBreaker official pmod, in 1A and 1B.
        DirectUSBResource("usb_pmod_1a", 0, d_p="47", d_n="45", pullup="4",
            attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
        DirectUSBResource("usb_pmod_1b", 0, d_p="34", d_n="31", pullup="38",
            attrs=Attrs(IO_STANDARD="SB_LVCMOS")),

        # Other USB layouts.
        DirectUSBResource("tnt_usb", 0,  d_p="31", d_n="34", pullup="38",
            attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
        DirectUSBResource("keckmann_usb", 0,  d_p="43", d_n="38", pullup="34",
            attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
    ]

    def __init__(self, *args, **kwargs):
        logging.warning("This platform is not officially supported, and thus not tested. Your results may vary.")
        logging.warning("Note also that this platform does not use the iCEBreaker's main USB port!")
        logging.warning("You'll need to connect a cable or pmod. See the platform file for more info.")

        super().__init__(*args, **kwargs)
        self.add_resources(self.additional_resources)



class IceBreakerBitsyPlatform(_IceBreakerBitsyPlatform, LUNAPlatform):
    name                   = "iCEBreaker Bitsy"
    clock_domain_generator = IceBreakerDomainGenerator
    default_usb_connection = "usb"

    def toolchain_program(self, products, name):
        dfu_util = os.environ.get("DFU_UTIL", "dfu-util")
        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call([dfu_util, "-d", "1209:6146", "-a", "0", "-R", "-D", bitstream_filename])
