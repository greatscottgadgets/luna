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


from nmigen import Elaboratable, ClockDomain, Module, ClockSignal, Instance, Signal, Const
from nmigen.build import Resource, Subsignal, Pins, Attrs, Clock, Connector, PinsN
from nmigen.vendor.lattice_ice40 import LatticeICE40Platform

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
        m.submodules.pll = Instance("SB_PLL40_CORE",
            i_REFERENCECLK  = ClockSignal("sync"),
            i_RESETB        = Const(1),
            i_BYPASS        = Const(0),

            o_PLLOUTCORE    = ClockSignal("usb"),

            # Create a 24 MHz PLL clock...
            p_FEEDBACK_PATH = "SIMPLE",
            p_DIVR          = 0,
            p_DIVF          = 15,
            p_DIVQ          = 5,
            p_FILTER_RANGE  = 4,

            # ... and divide it by half to get 12 MHz.
            p_PLLOUT_SELECT ="GENCLK_HALF"
        )

        # We'll use our 48MHz clock for everything _except_ the usb_io domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync"))
        ]

        return m


class FomuHackerPlatform(LatticeICE40Platform, LUNAPlatform):
    """ Base class for Fomu platforms. """

    default_clk = "clk48"
    name        = "Fomu Hacker"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = FomuDomainGenerator

    # We only have a direct connection on our USB lines, so use that for USB comms.
    default_usb_connection = "usb"

    device      = "iCE40UP5K"
    package     = "UWG30"
    default_clk = "clk48"
    resources   = [
        Resource("clk48", 0, Pins("F5", dir="i"),
                 Clock(48e6), Attrs(GLOBAL=True, IO_STANDARD="SB_LVCMOS")),

        Resource("led", 0, PinsN("C5"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("rgb_led", 0,
            Subsignal("r", PinsN("C5"), Attrs(IO_STANDARD="SB_LVCMOS")),
            Subsignal("g", PinsN("B5"), Attrs(IO_STANDARD="SB_LVCMOS")),
            Subsignal("b", PinsN("A5"),  Attrs(IO_STANDARD="SB_LVCMOS")),
        ),

        Resource("usb", 0,
            Subsignal("d_p",    Pins("A4")),
            Subsignal("d_n",    Pins("A2")),
            Subsignal("pullup", Pins("D5", dir="o")),
            Attrs(IO_STANDARD="SB_LVCMOS"),
        ),
    ]

    connectors = []


    def toolchain_program(self, products, name):
        """ Program the flash of a FomuHacker  board. """

        # Use the DFU bootloader to program the ECP5 bitstream.
        dfu_util = os.environ.get("DFU_UTIL", "dfu-util")
        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call([dfu_util, "-d", "1209:5bf0", "-D", bitstream_filename])



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

        Resource("led", 0, PinsN("41"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("rgb_led", 0,
            Subsignal("r", PinsN("40"), Attrs(IO_STANDARD="SB_LVCMOS")),
            Subsignal("g", PinsN("39"), Attrs(IO_STANDARD="SB_LVCMOS")),
            Subsignal("b", PinsN("41"),  Attrs(IO_STANDARD="SB_LVCMOS")),
        ),

        Resource("usb", 0,
            Subsignal("d_p",    Pins("34")),
            Subsignal("d_n",    Pins("37")),
            Subsignal("pullup", Pins("35", dir="o")),
            Attrs(IO_STANDARD="SB_LVCMOS"),
        ),

        # PMOD
        Resource("user_io", 0, PinsN("25"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("user_io", 1, PinsN("26"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("user_io", 2, PinsN("27"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("user_io", 3, PinsN("28"), Attrs(IO_STANDARD="SB_LVCMOS")),
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
