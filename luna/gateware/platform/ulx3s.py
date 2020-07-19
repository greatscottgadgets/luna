#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" ULX3S platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable,
as appropriate:

    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_12F_Platform"
    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_25F_Platform"
    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_45F_Platform"
    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_85F_Platform"
"""

import os
import subprocess

from abc import ABCMeta, abstractmethod

from nmigen import *
from nmigen.build import *
from nmigen.vendor.lattice_ecp5 import *

from .core import LUNAPlatform


class ULX3SDomainGenerator(Elaboratable):
    """ Stub clock domain generator; stands in for the typical LUNA one.

    This generator creates domains; but currently does not configure them.
    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Grab our default input clock.
        input_clock = platform.request(platform.default_clk, dir="i")

        # Create our domains; but don't do anything else for them, for now.
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        feedback = Signal()

        m.submodules.pll = Instance("EHXPLLL",
            i_RST=1,
            i_STDBY=0,
            i_CLKI=input_clock.i,
            i_PHASESEL0=0,
            i_PHASESEL1=0,
            i_PHASEDIR=1,
            i_PHASESTEP=1,
            i_PHASELOADREG=1,
            i_PLLWAKESYNC=0,
            i_ENCLKOP=0,
            i_CLKFB=feedback,

            #o_LOCK=locked,
            o_CLKOP=feedback,
            o_CLKOS=ClockSignal("sync"),
            o_CLKOS2=ClockSignal("usb"),

            p_PLLRST_ENA="DISABLED",
            p_INTFB_WAKE="DISABLED",
            p_STDBY_ENABLE="DISABLED",
            p_DPHASE_SOURCE="DISABLED",
            p_OUTDIVIDER_MUXA="DIVA",
            p_OUTDIVIDER_MUXB="DIVB",
            p_OUTDIVIDER_MUXC="DIVC",
            p_OUTDIVIDER_MUXD="DIVD",
            p_CLKI_DIV=5,
            p_CLKOP_ENABLE="ENABLED",
            p_CLKOS2_ENABLE="ENABLED",
            p_CLKOP_DIV=48,
            p_CLKOP_CPHASE=9,
            p_CLKOP_FPHASE=0,
            p_CLKOS_ENABLE="ENABLED",
            p_CLKOS_DIV=10,
            p_CLKOS_CPHASE=0,
            p_CLKOS_FPHASE=0,
            p_CLKOS2_DIV=40,
            p_CLKOS2_CPHASE=0,
            p_CLKOS2_FPHASE=0,
            p_FEEDBK_PATH="CLKOP",
            p_CLKFB_DIV=2,

            a_FREQUENCY_PIN_CLKI="25",
            a_FREQUENCY_PIN_CLKOP="48",
            a_FREQUENCY_PIN_CLKOS="48",
            a_FREQUENCY_PIN_CLKOS2="12",
            a_ICP_CURRENT="12",
            a_LPF_RESISTOR="8",
            a_MFG_ENABLE_FILTEROPAMP="1",
            a_MFG_GMCREF_SEL="2",

        )

        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync"))
        ]

        return m


class ULX3SPlatform(LatticeECP5Platform, LUNAPlatform, metaclass=ABCMeta):
    name                   = "ULX3S (12F)"
    package                = "BG381"
    speed                  = "8"
    default_clk            = "clk25"
    default_rst            = "rst"
    default_usb_connection = "usb"
    clock_domain_generator = ULX3SDomainGenerator

    @abstractmethod
    def device(self):
        pass

    resources = [

        Resource("clk25", 0, Pins("G2", dir="i"), Clock(25e6), Attrs(IO_TYPE="LVCMOS33")),
        Resource("rst",   0, Pins("R1", dir="i"), Attrs(IO_TYPE="LVCMOS33")),

        Resource("led", 0, Pins("B2", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 1, Pins("C2", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 2, Pins("C1", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 3, Pins("D2", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 4, Pins("D1", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 5, Pins("E2", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 6, Pins("E1", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 7, Pins("H3", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        Resource("serial", 0,
            Subsignal("tx", Pins("L4", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("rx", Pins("M1", dir="i"), Attrs(IO_TYPE="LVCMOS33"))
        ),

        Resource("spisdcard", 0,
            Subsignal("clk",  Pins("J1")),
            Subsignal("mosi", Pins("J3"), Attrs(PULLMODE="UP")),
            Subsignal("cs_n", Pins("H1"), Attrs(PULLMODE="UP")),
            Subsignal("miso", Pins("K2"), Attrs(PULLMODE="UP")),
            Attrs(SLEWRATE="FAST"),
            Attrs(IO_TYPE="LVCMOS33"),
        ),

        Resource("sdcard", 0,
            Subsignal("clk",  Pins("J1")),
            Subsignal("cmd",  Pins("J3"), Attrs(PULLMODE="UP")),
            Subsignal("data", Pins("K2 K1 H2 H1"), Attrs(PULLMODE="UP")),
            Attrs(IO_TYPE="LVCMOS33"), Attrs(SLEW="FAST")
        ),

        Resource("sdram_clock", 0, Pins("F19"),
            Attrs(PULLMODE="NONE"),
            Attrs(DRIVE="4"),
            Attrs(SLEWRATE="FAST"),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("sdram", 0,
            Subsignal("a",     Pins(
                "M20 M19 L20 L19 K20 K19 K18 J20"
                "J19 H20 N19 G20 G19")),
            Subsignal("dq",    Pins(
                "J16 L18 M18 N18 P18 T18 T17 U20"
                "E19 D20 D19 C20 E18 F18 J18 J17")),
            Subsignal("we_n",  Pins("T20")),
            Subsignal("ras_n", Pins("R20")),
            Subsignal("cas_n", Pins("T19")),
            Subsignal("cs_n",  Pins("P20")),
            Subsignal("cke",   Pins("F20")),
            Subsignal("ba",    Pins("P19 N20")),
            Subsignal("dm",    Pins("U19 E20")),
            Attrs(PULLMODE="NONE"),
            Attrs(DRIVE="4"),
            Attrs(SLEWRATE="FAST"),
            Attrs(IO_TYPE="LVCMOS33"),
        ),

        Resource("wifi_gpio0", 0, Pins("L2", dir="o"), Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")),

        Resource("ext0p", 0, Pins("B11"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("ext1p", 0, Pins("A10"), Attrs(IO_TYPE="LVCMOS33")),

        Resource("gpio", 0,
            Subsignal("p", Pins("B11")),
            Subsignal("n", Pins("C11")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("gpio", 1,
            Subsignal("p", Pins("A10")),
            Subsignal("n", Pins("A11")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("gpio", 2,
            Subsignal("p", Pins("A9")),
            Subsignal("n", Pins("B10")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("gpio", 3,
            Subsignal("p", Pins("B9")),
            Subsignal("n", Pins("C10")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        Resource("usb", 0,
            Subsignal("d_p", Pins("D15")),
            Subsignal("d_n", Pins("E15")),
            Subsignal("pullup", Pins("B12 C12", dir="o")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
    ]

    # TODO
    connectors = []

    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = dict(ecppack_opts="--compress")
        overrides.update(kwargs)
        return super().toolchain_prepare(fragment, name, **overrides)


    def toolchain_program(self, products, name):
        tool = os.environ.get("OPENFPGALOADER", "openFPGALoader")
        with products.extract("{}.bit".format(name)) as bitstream_filename:
            subprocess.check_call([tool, "-b", "ulx3s", '-m', bitstream_filename])



# Semantic alias.
class ULX3S_12F_Platform(ULX3SPlatform):
    name                   = "ULX3S (12F)"
    device                 = "LFE5U-12F"


class ULX3S_25F_Platform(ULX3SPlatform):
    name                   = "ULX3S (25F)"
    device                 = "LFE5U-25F"

class ULX3S_45F_Platform(ULX3SPlatform):
    name                   = "ULX3S (45F)"
    device                 = "LFE5U-45F"


class ULX3S_85F_Platform(ULX3SPlatform):
    name                   = "ULX3S (85F)"
    device                 = "LFE5U-85F"
