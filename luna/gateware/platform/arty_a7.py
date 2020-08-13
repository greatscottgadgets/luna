#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" LambdaConcept board platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.lambdaconcept:USB2SnifferPlatform"
or

    > export LUNA_PLATFORM="luna.gateware.platform.lambdaconcept:ECPIX5PlatformRev02"
"""

import os
import subprocess

from nmigen import *
from nmigen.build import *
from nmigen.vendor.xilinx_7series import Xilinx7SeriesPlatform
from nmigen_boards.resources import *

from .core import LUNAPlatform


class StubClockDomainGenerator(Elaboratable):
    """ Stub clock domain generator; stands in for the typical LUNA one.

    This generator creates domains; but currently does not configuration.
    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()
        m.domains.clk48   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        locked = Signal()
        pll_fb = Signal()
        clkin = platform.request(platform.default_clk, dir="i")

        m.submodules.pll = Instance("PLLE2_ADV",
                                    p_BANDWIDTH            = "OPTIMIZED",
                                    p_COMPENSATION         = "ZHOLD",
                                    p_STARTUP_WAIT         = "FALSE",
                                    p_DIVCLK_DIVIDE        = 1,
                                    p_CLKFBOUT_MULT        = 12,
                                    p_CLKFBOUT_PHASE       = 0.000,
                                    p_CLKOUT0_DIVIDE       = 100,
                                    p_CLKOUT0_PHASE        = 0.000,
                                    p_CLKOUT0_DUTY_CYCLE   = 0.500,
                                    p_CLKOUT1_DIVIDE       = 25,
                                    p_CLKOUT1_PHASE        = 0.000,
                                    p_CLKOUT1_DUTY_CYCLE   = 0.500,
                                    p_CLKIN1_PERIOD        = 10.000,
 	                            i_CLKFBIN              = pll_fb,
                                    o_CLKFBOUT             = pll_fb,
	                            i_CLKIN1               = clkin,
	                            o_CLKOUT0              = ClockSignal("usb"),   # 12MHz
                                    o_CLKOUT1              = ClockSignal("clk48"), # 48MHz
	                            o_LOCKED               = locked,
        )

        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("clk48")),
            ClockSignal("fast")    .eq(ClockSignal("clk48")),

            ResetSignal("clk48")   .eq(~locked),
            ResetSignal("usb")     .eq(~locked),
            ResetSignal("usb_io")  .eq(~locked),
            ResetSignal("fast")    .eq(~locked),
        ]

        return m


class ArtyA7Platform(Xilinx7SeriesPlatform, LUNAPlatform):
    """ Board description for ArcticSerdes board. """

    name        = "ArcticSerdes"

    device      = "xc7a35ti"
    package     = "csg324"
    speed       = "1L"
    default_clk = "clk100"

    clock_domain_generator = StubClockDomainGenerator

    default_usb_connection = "usb"

    #
    # I/O resources.
    #
    resources   = [
        Resource("clk100", 0, Pins("E3", dir="i"),
                 Clock(100e6), Attrs(IOSTANDARD="LVCMOS33")),
        DirectUSBResource(0, d_p="G13", d_n="B11", pullup="A11", attrs=Attrs(IOStandard="LVCMOS33")),
    ]

    connectors = []


    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            "script_before_bitstream":
                "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]",
            "script_after_bitstream":
                "write_cfgmem -force -format bin -interface spix4 -size 16 "
                "-loadbit \"up 0x0 {name}.bit\" -file {name}.bin".format(name=name),
        }
        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)

    def toolchain_program(self, products, name):
        xc3sprog = os.environ.get("XC3SPROG", "xc3sprog")
        with products.extract("{}.bit".format(name)) as bitstream_filename:
            subprocess.run([xc3sprog, "-c", "nexys4", bitstream_filename], check=True)
