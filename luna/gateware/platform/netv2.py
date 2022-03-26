#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" NeTV2 Platform Definition

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.netv2:NeTV2Platform"

The NeTV2 has a fixed pull-up resistor on D-; which prevents it from being used as a
FS device. To use the platform for full-speed USB, you'll need to move the resistor
populated as R23 over to R24.
"""

import os
import subprocess

from amaranth import *
from amaranth.build import *
from amaranth.vendor.xilinx_7series import Xilinx7SeriesPlatform

from amaranth_boards.resources import *

from ..interface.pipe       import AsyncPIPEInterface
from ..interface.serdes_phy import XC7GTPSerDesPIPE

from .core import LUNAPlatform


class NeTV2ClockDomainGenerator(Elaboratable):
    """ Clock/Reset Controller for the NeTV2. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains; but don't do anything else for them, for now.
        m.domains.usb     = ClockDomain()
        m.domains.usb_io  = ClockDomain()
        m.domains.sync    = ClockDomain()
        m.domains.ss      = ClockDomain()
        m.domains.fast    = ClockDomain()

        # Grab our main clock.
        clk50 = platform.request(platform.default_clk)

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
            p_CLKFBOUT_MULT        = 24,
            p_CLKFBOUT_PHASE       = 0.000,
            p_CLKOUT0_DIVIDE       = 100,
            p_CLKOUT0_PHASE        = 0.000,
            p_CLKOUT0_DUTY_CYCLE   = 0.500,
            p_CLKOUT1_DIVIDE       = 25,
            p_CLKOUT1_PHASE        = 0.000,
            p_CLKOUT1_DUTY_CYCLE   = 0.500,
            p_CLKIN1_PERIOD        = 20.000,
            i_CLKFBIN              = usb2_feedback,
            o_CLKFBOUT             = usb2_feedback,
            i_CLKIN1               = clk50,
            o_CLKOUT0              = clk12,
            o_CLKOUT1              = clk48,
            o_LOCKED               = usb2_locked,
        )


        # USB3 PLL connections.
        clk16         = Signal()
        clk125        = Signal()
        clk250        = Signal()
        usb3_locked   = Signal()
        usb3_feedback = Signal()
        m.submodules.usb3_pll = Instance("PLLE2_ADV",
            p_BANDWIDTH            = "OPTIMIZED",
            p_COMPENSATION         = "ZHOLD",
            p_STARTUP_WAIT         = "FALSE",
            p_DIVCLK_DIVIDE        = 1,
            p_CLKFBOUT_MULT        = 20,    # VCO = 1000 MHz
            p_CLKFBOUT_PHASE       = 0.000,
            p_CLKOUT0_DIVIDE       = 4,     # CLKOUT0 = 250 MHz (1000/4)
            p_CLKOUT0_PHASE        = 0.000,
            p_CLKOUT0_DUTY_CYCLE   = 0.500,
            p_CLKOUT1_DIVIDE       = 8,     # CLKOUT1 = 125 MHz (1000/8)
            p_CLKOUT1_PHASE        = 0.000,
            p_CLKOUT1_DUTY_CYCLE   = 0.500,
            p_CLKOUT2_DIVIDE       = 64,    # CLKOUT2 = 16 MHz  (1000/64)
            p_CLKOUT2_PHASE        = 0.000,
            p_CLKOUT2_DUTY_CYCLE   = 0.500,
            p_CLKIN1_PERIOD        = 20.000,
            i_CLKFBIN              = usb3_feedback,
            o_CLKFBOUT             = usb3_feedback,
            i_CLKIN1               = clk50,
            o_CLKOUT0              = clk250,
            o_CLKOUT1              = clk125,
            o_CLKOUT2              = clk16,
            o_LOCKED               = usb3_locked,
        )

        # Connect up our clock domains.
        m.d.comb += [
            ClockSignal("usb")      .eq(clk12),
            ClockSignal("usb_io")   .eq(clk48),
            ClockSignal("sync")     .eq(clk125),
            ClockSignal("ss")       .eq(clk125),
            ClockSignal("fast")     .eq(clk250),

            ResetSignal("usb")      .eq(~usb2_locked),
            ResetSignal("usb_io")   .eq(~usb2_locked),
            ResetSignal("sync")     .eq(~usb3_locked),
            ResetSignal("ss")       .eq(~usb3_locked),
            ResetSignal("fast")     .eq(~usb3_locked),
        ]

        return m


class NeTV2SuperSpeedPHY(AsyncPIPEInterface):
    """ Superspeed PHY configuration for the NeTV2. """

    SS_FREQUENCY   = 125e6
    FAST_FREQUENCY = 250e6


    def __init__(self, platform):

        # Grab the I/O that implements our SerDes interface...
        serdes_io = platform.request("serdes", dir={'tx':"-", 'rx':"-"})

        # Use it to create our soft PHY...
        serdes_phy = XC7GTPSerDesPIPE(
            tx_pads             = serdes_io.tx,
            rx_pads             = serdes_io.rx,
            refclk_frequency    = self.FAST_FREQUENCY,
            ss_clock_frequency  = self.SS_FREQUENCY,
        )

        # ... and bring the PHY interface signals to the MAC domain.
        super().__init__(serdes_phy, width=4, domain="ss")


    def elaborate(self, platform):
        m = super().elaborate(platform)

        # Patch in our soft PHY as a submodule.
        m.submodules.phy = self.phy

        # Drive the PHY reference clock with our fast generated clock.
        m.d.comb += self.clk.eq(ClockSignal("fast"))

        # This board does not have a way to detect Vbus, so assume it's always present.
        m.d.comb += self.phy.power_present.eq(1)

        return m



class NeTV2Platform(Xilinx7SeriesPlatform, LUNAPlatform):
    """ Board description for the NeTV2. """

    name        = "NeTV2"

    device      = "xc7a35t"
    package     = "fgg484"
    speed       = "2"

    default_clk = "clk50"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = NeTV2ClockDomainGenerator

    # Use our direct USB connection for USB2, and our SerDes for USB3.
    default_usb_connection = "usb"
    default_usb3_phy       = NeTV2SuperSpeedPHY

    #
    # I/O resources.
    #

    resources = [
        Resource("clk50", 0, Pins("J19"), Attrs(IOSTANDARD="LVCMOS33"), Clock(50e6)),

        # R/G leds
        *LEDResources(pins="M21 N20 L21 AA21 R19 M16", attrs=Attrs(IOSTANDARD="LVCMOS33"), invert=True),

        # Comms
        #DirectUSBResource(0, d_p="C14", d_n="C15", attrs=Attrs(IOSTANDARD="LVCMOS33")),

        # XXX
        DirectUSBResource(0, d_p="A15", d_n="A14", pullup="C17", attrs=Attrs(IOSTANDARD="LVCMOS33")),

        UARTResource(0, rx="E13", tx="E14", attrs=Attrs(IOSTANDARD="LVCMOS33")),

        # PCIe gold fingers (for USB3)
        Resource("serdes", 0,
            Subsignal("tx", DiffPairs("D5", "C5")),
            Subsignal("rx", DiffPairs("D11", "C11")),
        ),

        # User I/O (labeled "hax")
        Resource("user_io", 0, Pins("B15"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 1, Pins("B16"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 2, Pins("B13"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 3, Pins("A15"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 4, Pins("A16"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 5, Pins("A13"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 6, Pins("A14"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 7, Pins("B17"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 8, Pins("A18"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 9, Pins("C17"), Attrs(IOSTANDARD="LVCMOS33")),
    ]

    connectors = []


    def toolchain_prepare(self, fragment, name, **kwargs):

        extra_constraints = [
            # Allow use to drive our SerDes from FPGA fabric.
            "set_property SEVERITY {Warning} [get_drc_checks REQP-49]"
        ]

        overrides = {
            "script_before_bitstream":
                "set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]",
            "add_constraints": "\n".join(extra_constraints)
        }
        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)


    #
    # FIXME: figure out a better tool to use for running with the NeTV attached
    # to a raspberry pi
    #
    def toolchain_program(self, products, name):
        xc3sprog = os.environ.get("XC3SPROG", "xc3sprog")
        with products.extract("{}.bit".format(name)) as bitstream_file:
            subprocess.check_call([xc3sprog, "-c", "ft4232h", bitstream_file])


