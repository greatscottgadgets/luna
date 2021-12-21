#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Arty A7 Platform Definition

The full Arty A7 does not have an explicit USB port. Instead, you'll need to connect a USB breakout.
The Arty A7 is an -unsupported- platform! To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.arty_a7:ArtyA7Platform"
"""

import os
import logging
import subprocess

from amaranth import *
from amaranth.build import *

from amaranth_boards.arty_a7   import ArtyA7Platform as _CoreArtyA7Platform
from amaranth_boards.resources import *

from .core import LUNAPlatform

class ArtyA7ClockDomainGenerator(Elaboratable):
    """ Clock/Reset Controller for the Arty A7. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains; but don't do anything else for them, for now.
        m.domains.usb     = ClockDomain()
        m.domains.usb_io  = ClockDomain()
        m.domains.sync    = ClockDomain()

        # Grab our main clock.
        clk100 = platform.request(platform.default_clk)

        # USB2 PLL connections.
        clk12         = Signal()
        clk48         = Signal()
        usb2_locked   = Signal()
        usb2_feedback = Signal()
        m.submodules.usb2_pll = Instance("PLLE2_ADV",
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
            i_CLKFBIN              = usb2_feedback,
            o_CLKFBOUT             = usb2_feedback,
            i_CLKIN1               = clk100,
            o_CLKOUT0              = clk12,
            o_CLKOUT1              = clk48,
            o_LOCKED               = usb2_locked,
        )

        # Connect up our clock domains.
        m.d.comb += [
            ClockSignal("usb")      .eq(clk12),
            ClockSignal("usb_io")   .eq(clk48),

            ResetSignal("usb")      .eq(~usb2_locked),
            ResetSignal("usb_io")   .eq(~usb2_locked),
        ]

        return m



class ArtyA7Platform(_CoreArtyA7Platform, LUNAPlatform):
    """ Board description for the Arty A7. """

    name        = "Arty A7"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = ArtyA7ClockDomainGenerator

    # Use our direct USB connection for USB2
    default_usb_connection = "usb_pmod_b"

    #
    # I/O resources.
    #

    additional_resources   = [
        DirectUSBResource("usb_pmod_a", 0, d_p="G13", d_n="B11", pullup="A11", attrs=Attrs(IOStandard="LVCMOS33")),
        DirectUSBResource("usb_pmod_b", 0, d_p="E15", d_n="E16", pullup="D15", attrs=Attrs(IOStandard="LVCMOS33")),
        DirectUSBResource("usb_pmod_c", 0, d_p="U12", d_n="V12", pullup="V10", attrs=Attrs(IOStandard="LVCMOS33")),
        DirectUSBResource("usb_pmod_d", 0, d_p="D4",  d_n="D3",  pullup="F4",  attrs=Attrs(IOStandard="LVCMOS33")),
    ]

    connectors = []


    def __init__(self, *args, **kwargs):
        logging.warning("This platform is not officially supported, and thus not tested. Your results may vary.")
        logging.warning("Note also that this platform does not use the Arty's main USB port!")
        logging.warning("You'll need to connect a cable or pmod. See the platform file for more info.")

        super().__init__(*args, **kwargs)
        self.add_resources(self.additional_resources)



    def toolchain_prepare(self, fragment, name, **kwargs):

        overrides = {
            "script_before_bitstream":
                "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]",
            "script_after_bitstream":
                "write_cfgmem -force -format bin -interface spix4 -size 16 "
                "-loadbit \"up 0x0 {name}.bit\" -file {name}.bin".format(name=name),
            "add_constraints":
                "set_clock_groups -asynchronous -group [get_clocks -of_objects [get_pins -regexp .*/pll/CLKOUT0]] -group [get_clocks -of_objects [get_pins -regexp .*/pll/CLKOUT1]]",
        }

        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)
