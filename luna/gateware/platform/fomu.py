#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" fomu Platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.fomu:FomuHackerPlatform"
"""

import os
import subprocess

from amaranth import *
from amaranth.build import *
from amaranth.vendor.lattice_ice40 import LatticeICE40Platform

from amaranth_boards.fomu_hacker import FomuHackerPlatform as _FomuHackerPlatform
from amaranth_boards.fomu_pvt import FomuPVTPlatform as _FomuPVTPlatform
from amaranth_boards.resources import *

from .core import LUNAPlatform


class FomuDomainGenerator(Elaboratable):
    """ Stub clock domain generator; stands in for the typical LUNA one.

    This generator creates domains; but currently does not configure them.
    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains...
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        # ... and create our 12 MHz USB clock.
        clk12 = Signal()

        m.submodules.pll = Instance("SB_PLL40_CORE",
            i_REFERENCECLK  = ClockSignal("sync"),
            i_RESETB        = Const(1),
            i_BYPASS        = Const(0),

            o_PLLOUTCORE    = clk12,

            # Create a 24 MHz PLL clock...
            p_FEEDBACK_PATH = "SIMPLE",
            p_DIVR          = 0,
            p_DIVF          = 15,
            p_DIVQ          = 5,
            p_FILTER_RANGE  = 4,

            # ... and divide it by half to get 12 MHz.
            p_PLLOUT_SELECT ="GENCLK_HALF"
        )

        # Relax the 12MHz clock down to 12MHz.
        platform.add_clock_constraint(clk12, 12e6)

        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb")     .eq(clk12),
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync"))
        ]

        return m


class FomuHackerPlatform(_FomuHackerPlatform, LUNAPlatform):
    name                   = "Fomu Hacker"
    clock_domain_generator = FomuDomainGenerator
    default_usb_connection = "usb"


class FomuPVT(_FomuPVTPlatform, LUNAPlatform):
    name                   = "Fomu PVT/Production"
    clock_domain_generator = FomuDomainGenerator
    default_usb_connection = "usb"


class FomuEVTPlatform(LatticeICE40Platform, LUNAPlatform):
    """ Platform for the Fomu EVT platforms. """

    default_clk = "clk48"
    name        = "Fomu EVT"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = FomuDomainGenerator

    # We only have a direct connection on our USB lines, so use that for USB comms.
    default_usb_connection = "usb"

    device      = "iCE40UP5K"
    package     = "SG48"

    default_clk = "clk48"
    resources   = [
        Resource("clk48", 0, Pins("44", dir="i"),
                 Clock(48e6), Attrs(GLOBAL=True, IO_STANDARD="SB_LVCMOS")),

        LEDResources(pins="41", invert=True, attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
        RGBLEDResource(0, r="40", g="39", b="41", invert=True, attrs=Attrs(IO_STANDARD="SB_LVCMOS")),

        DirectUSBResource(0, d_p="34", d_n="37", pullup="35", attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
    ]

    connectors = []


    def toolchain_program(self, products, name):
        """ Program the FPGA of an Fomu EVT board. """

        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call(["fomu-flash", "-f", bitstream_filename])


    def toolchain_flash(self, products, name="top"):
        """ Flash the SPI flash of an Fomu EVT board. """

        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call(["fomu-flash", "-w", bitstream_filename])
