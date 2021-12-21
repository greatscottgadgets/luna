#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" OrangeCrab platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.orangecrab:OrangeCrabPlatformR0D1"
    > export LUNA_PLATFORM="luna.gateware.platform.orangecrab:OrangeCrabPlatformR0D2"
"""

import os
import subprocess

from amaranth import *
from amaranth.build import *
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform

from amaranth_boards.orangecrab_r0_1 import OrangeCrabR0_1Platform as _OrangeCrabR0D1Platform
from amaranth_boards.orangecrab_r0_2 import OrangeCrabR0_2Platform as _OrangeCrabR0D2Platform

from .core import LUNAPlatform

__all__ = ["OrangeCrabPlatformR0D1", "OrangeCrabPlatformR0D2"]


class OrangeCrabDomainGenerator(Elaboratable):
    """ Stub clock domain generator; stands in for the typical LUNA one.

    This generator creates domains; but currently does not configure them.
    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()
        locked = Signal()

        # Grab our default input clock.
        input_clock = platform.request(platform.default_clk, dir="i")

        # Create our domains; but don't do anything else for them, for now.
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=input_clock,

                # Generated clock outputs.
                o_CLKOP=ClockSignal("sync"),
                o_CLKOS=ClockSignal("usb"),

                # Status.
                o_LOCK=locked,

                # PLL parameters...
                p_PLLRST_ENA="DISABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_CLKOS3_FPHASE=0,
                p_CLKOS3_CPHASE=0,
                p_CLKOS2_FPHASE=0,
                p_CLKOS2_CPHASE=7,
                p_CLKOS_FPHASE=0,
                p_CLKOS_CPHASE=5,
                p_CLKOP_FPHASE=0,
                p_CLKOP_CPHASE=5,
                p_PLL_LOCK_MODE=0,
                p_CLKOS_TRIM_DELAY="0",
                p_CLKOS_TRIM_POL="FALLING",
                p_CLKOP_TRIM_DELAY="0",
                p_CLKOP_TRIM_POL="FALLING",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKOS3_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXC="DIVC",
                p_CLKOS2_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXB="DIVB",
                p_CLKOS_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOS3_DIV=1,
                p_CLKOS2_DIV=8,
                p_CLKOS_DIV=48,
                p_CLKOP_DIV=12,
                p_CLKFB_DIV=1,
                p_CLKI_DIV=1,
                p_FEEDBK_PATH="CLKOP",

                # Internal feedback.
                i_CLKFB=ClockSignal("sync"),

                # Control signals.
                i_RST=0,
                i_PHASESEL0=0,
                i_PHASESEL1=0,
                i_PHASEDIR=1,
                i_PHASESTEP=1,
                i_PHASELOADREG=1,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS=0,
                i_ENCLKOS2=0,
                i_ENCLKOS3=0,

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="48.000000",
                a_FREQUENCY_PIN_CLKOS="48.000000",
                a_FREQUENCY_PIN_CLKOP="12.000000",
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8"
        )

        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync")),

            ResetSignal("sync")    .eq(~locked),
            ResetSignal("usb")     .eq(~locked),
            ResetSignal("usb_io")  .eq(~locked),
            ResetSignal("fast")    .eq(~locked),
        ]

        return m


class OrangeCrabPlatformR0D1(_OrangeCrabR0D1Platform, LUNAPlatform):
    name                   = "OrangeCrab r0.1"
    clock_domain_generator = OrangeCrabDomainGenerator
    default_usb_connection = "usb"

    # Add I/O aliases with standard LUNA naming.
    additional_resources = [

        # User I/O
        Resource("user_io",  0, Pins("N17"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io",  1, Pins("M18"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io",  2, Pins("B10"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io",  3, Pins("B9") , Attrs(IO_TYPE="LVCMOS33")),

        # Create aliases for our LEDs with standard naming.
        Resource("led", 0, Pins("V17", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 1, Pins("T14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 2, Pins("J3", dir="o"),  Attrs(IO_TYPE="LVCMOS33")),
    ]

    # Create our semantic aliases.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_resources(self.additional_resources)


class OrangeCrabPlatformR0D2(_OrangeCrabR0D2Platform, LUNAPlatform):
    name                   = "OrangeCrab r0.2"
    clock_domain_generator = OrangeCrabDomainGenerator
    default_usb_connection = "usb"

    # Add I/O aliases with standard LUNA naming.
    additional_resources = [

        # User I/O
        Resource("user_io",  0, Pins("N17"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io",  1, Pins("M18"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io",  2, Pins("C10"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io",  3, Pins("C9") , Attrs(IO_TYPE="LVCMOS33")),

        # Create aliases for our LEDs with standard naming.
        Resource("led", 0, Pins("K4", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 1, Pins("M3", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 2, Pins("J3", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

    ]

    # Create our semantic aliases.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_resources(self.additional_resources)
