#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" LogicBone Platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.logicbone:LogicbonePlatform"
or
    > export LUNA_PLATFORM="luna.gateware.platform.logicbone:Logicbone85FPlatform"
"""

import os
import subprocess

from amaranth import *
from amaranth.lib.cdc import ResetSynchronizer
from amaranth.build import *
from amaranth.vendor.lattice_ecp5 import *

from amaranth_boards.logicbone import LogicbonePlatform as _CoreLogicbonePlatform
from amaranth_boards.logicbone import Logicbone85FPlatform as _CoreLogicbone85FPlatform
from amaranth_boards.resources import *

from ..interface.pipe       import AsyncPIPEInterface
from ..interface.serdes_phy import ECP5SerDesPIPE

from .core import LUNAPlatform


__all__ = ["LogicbonePlatform", "Logicbone85FPlatform"]


class LogicboneDomainGenerator(Elaboratable):
    """ Simple clock domain generator for the Logicbone. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Grab our default input clock.
        clk25 = platform.request(platform.default_clk, dir="i")
        reset = Const(0)

        # Create our domains; but don't do anything else for them, for now.
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.ss     = ClockDomain()
        m.domains.fast   = ClockDomain()

        # USB FS PLL
        feedback    = Signal()
        usb2_locked = Signal()
        m.submodules.fs_pll = Instance("EHXPLLL",

                # Status.
                o_LOCK=usb2_locked,

                # PLL parameters...
                p_PLLRST_ENA="ENABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_OUTDIVIDER_MUXB="DIVB",
                p_OUTDIVIDER_MUXC="DIVC",
                p_OUTDIVIDER_MUXD="DIVD",

                p_CLKI_DIV = 5,
                p_CLKOP_ENABLE = "ENABLED",
                p_CLKOP_DIV = 16,
                p_CLKOP_CPHASE = 15,
                p_CLKOP_FPHASE = 0,

                p_CLKOS_DIV = 10,
                p_CLKOS_CPHASE = 0,
                p_CLKOS_FPHASE = 0,


                p_CLKOS2_ENABLE = "ENABLED",
                p_CLKOS2_DIV = 10,
                p_CLKOS2_CPHASE = 0,
                p_CLKOS2_FPHASE = 0,

                p_CLKOS3_ENABLE = "ENABLED",
                p_CLKOS3_DIV = 40,
                p_CLKOS3_CPHASE = 5,
                p_CLKOS3_FPHASE = 0,

                p_FEEDBK_PATH = "CLKOP",
                p_CLKFB_DIV = 6,

                # Clock in.
                i_CLKI=clk25,

                # Internal feedback.
                i_CLKFB=feedback,

                # Control signals.
                i_RST=reset,
                i_PHASESEL0=0,
                i_PHASESEL1=0,
                i_PHASEDIR=1,
                i_PHASESTEP=1,
                i_PHASELOADREG=1,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS2=0,

                # Generated clock outputs.
                o_CLKOP=feedback,
                o_CLKOS2=ClockSignal("usb_io"),
                o_CLKOS3=ClockSignal("usb"),

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="25",
                a_FREQUENCY_PIN_CLKOP="48",
                a_FREQUENCY_PIN_CLKOS="48",
                a_FREQUENCY_PIN_CLKOS2="12",
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8",
                a_MFG_ENABLE_FILTEROPAMP="1",
                a_MFG_GMCREF_SEL="2"
        )

        # Generate the clocks we need for running our SerDes.
        feedback     = Signal()
        usb3_locked  = Signal()
        m.submodules.ss_pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=clk25,

                # Generated clock outputs.
                o_CLKOP=feedback,
                o_CLKOS= ClockSignal("ss"),
                o_CLKOS2=ClockSignal("fast"),

                # Status.
                o_LOCK=usb3_locked,

                # PLL parameters...
                p_CLKI_DIV=1,
                p_PLLRST_ENA="ENABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_CLKOS3_FPHASE=0,
                p_CLKOS3_CPHASE=0,
                p_CLKOS2_FPHASE=0,
                p_CLKOS2_CPHASE=5,
                p_CLKOS_FPHASE=0,
                p_CLKOS_CPHASE=5,
                p_CLKOP_FPHASE=0,
                p_CLKOP_CPHASE=19,
                p_PLL_LOCK_MODE=0,
                p_CLKOS_TRIM_DELAY="0",
                p_CLKOS_TRIM_POL="FALLING",
                p_CLKOP_TRIM_DELAY="0",
                p_CLKOP_TRIM_POL="FALLING",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKOS3_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXC="DIVC",
                p_CLKOS2_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXB="DIVB",
                p_CLKOS_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOS3_DIV=1,
                p_CLKOS2_DIV=2,
                p_CLKOS_DIV=4,
                p_CLKOP_DIV=20,
                p_CLKFB_DIV=1,
                p_FEEDBK_PATH="CLKOP",

                # Internal feedback.
                i_CLKFB=feedback,

                # Control signals.
                i_RST=reset,
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
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8"
        )



        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("sync")    .eq(ClockSignal("ss")),

            # ResetSignal("usb")     .eq(~usb2_locked),
            ResetSignal("usb_io")  .eq(ResetSignal("usb")),
            # ResetSignal("ss")      .eq(~usb3_locked),
            ResetSignal("sync")    .eq(ResetSignal("ss")),
            ResetSignal("fast")    .eq(ResetSignal("ss")),
        ]

        # LOCK is an asynchronous output of the EXHPLL block.
        # Reset USB 2 and USB 3 domains together to avoid issues transferring data between these domains
        # (e.g. when the ILA is being used).
        m.submodules += ResetSynchronizer(~usb2_locked | ~usb3_locked, domain="usb")
        m.submodules += ResetSynchronizer(~usb2_locked | ~usb3_locked, domain="ss")

        return m


class LogicboneSuperSpeedPHY(AsyncPIPEInterface):
    """ Superspeed PHY configuration for the Logicbone. """

    SS_FREQUENCY   = 125e6
    FAST_FREQUENCY = 250e6

    SERDES_CHANNEL = 0


    def __init__(self, platform):

        # Grab the I/O that implements our SerDes interface...
        serdes_io = platform.request("serdes", self.SERDES_CHANNEL, dir={'tx':"-", 'rx':"-"})

        # Use it to create our soft PHY...
        serdes_phy = ECP5SerDesPIPE(
            tx_pads             = serdes_io.tx,
            rx_pads             = serdes_io.rx,
            channel             = self.SERDES_CHANNEL,
            refclk_frequency    = self.FAST_FREQUENCY,
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



class LogicbonePlatform(_CoreLogicbonePlatform, LUNAPlatform):
    clock_domain_generator = LogicboneDomainGenerator
    default_usb3_phy       = LogicboneSuperSpeedPHY
    default_usb_connection = "usb"


class Logicbone85FPlatform(_CoreLogicbone85FPlatform, LUNAPlatform):
    clock_domain_generator = LogicboneDomainGenerator
    default_usb3_phy       = LogicboneSuperSpeedPHY
    default_usb_connection = "usb"
