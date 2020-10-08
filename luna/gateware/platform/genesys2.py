#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Digilent Nexys Video Platform Files

This is an unsupported platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.genesys2:Genesys2Platform"

This platform has no built-in USB resources; but has a FMC that can be used to connect up
TUSB1310A PHYs, which offer ULPI USB2 and PIPE USB3. They also have pmods, which can be
connected up via our gateware PHY.
"""

import os
import logging

from nmigen import *
from nmigen.build import *

from nmigen_boards.genesys2 import Genesys2Platform as _CoreGenesys2Platform
from nmigen_boards.resources import *

from ..architecture.car import PHYResetController
from ..interface.pipe   import GearedPIPEInterface

from .core import LUNAPlatform


class Genesys2ClockDomainGenerator(Elaboratable):
    """ Clock/Reset Controller for the Genesys2. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Synthetic clock domains.
        m.domains.sync     = ClockDomain(reset_less=True)
        m.domains.fast     = ClockDomain()

        # USB 2 clock domains.
        m.domains.usb      = ClockDomain()
        m.domains.usb_io   = ClockDomain()

        # 250 MHz I/O boundary clocks
        m.domains.ss_io         = ClockDomain()
        m.domains.ss_io_shifted = ClockDomain()

        # 125 MHz ss clocks
        m.domains.ss            = ClockDomain()
        m.domains.ss_shifted    = ClockDomain()

        # USB2 connections.
        # To meet our PHY's timing, we'll need to sh ift the USB clock's phase a bit,
        # so we sample at a valid point and don't violate setup or hold.
        usb2_locked   = Signal()
        usb2_feedback = Signal()
        m.submodules.usb2_pll = Instance("PLLE2_ADV",
            p_BANDWIDTH            = "OPTIMIZED",
            p_COMPENSATION         = "ZHOLD",
            p_STARTUP_WAIT         = "FALSE",
            p_DIVCLK_DIVIDE        = 1,
            p_CLKFBOUT_MULT        = 14,
            p_CLKFBOUT_PHASE       = 0.000,
            p_CLKOUT0_DIVIDE       = 14,
            p_CLKOUT0_PHASE        = 270.000,
            p_CLKOUT0_DUTY_CYCLE   = 0.500,
            i_CLKFBIN              = usb2_feedback,
            o_CLKFBOUT             = usb2_feedback,
            i_CLKIN1               = ClockSignal("usb_io"),  # 60 MHz
            p_CLKIN1_PERIOD        = 16.67,
            o_CLKOUT0              = ClockSignal("usb"),     # 60 MHz
            o_LOCKED               = usb2_locked,
        )

        # Create a reset controller for our USB2 PHY.
        m.submodules.phy_reset = phy_reset = PHYResetController(clock_frequency=200e6)

        #
        # Create our USB3 PHY clocks.
        #
        usb3_locked        = Signal()
        usb3_feedback      = Signal()
        m.submodules.usb3_pll = Instance("PLLE2_BASE",
            p_STARTUP_WAIT         = "FALSE",

            # 250 MHz input from PCLK, VCO at 1GHz
            i_CLKIN1               = ClockSignal("ss_io"),
            p_REF_JITTER1          = 0.01,
            p_CLKIN1_PERIOD        = 4.0,
            p_DIVCLK_DIVIDE        = 1,
            p_CLKFBOUT_MULT        = 4,
            p_CLKFBOUT_PHASE       = 0.000,

            o_LOCKED               = usb3_locked,

            # Clock feedback.
            i_CLKFBIN              = usb3_feedback,
            o_CLKFBOUT             = usb3_feedback,

            # CLKOUT0 = 125 MHz (1/2 PCLK)
            p_CLKOUT0_DIVIDE       = 8,
            p_CLKOUT0_PHASE        = 0.0,
            o_CLKOUT0              = ClockSignal("ss"),

            # CLKOUT1 = 125 MHz / 8ns (1/2 PCLK + phase delay)
            # We want to sample our input after 2ns. This is >=90 degrees of this clock.
            p_CLKOUT1_DIVIDE       = 8,
            p_CLKOUT1_PHASE        = 180.0,
            o_CLKOUT1              = ClockSignal("ss_shifted"),

            # CLKOUT2 = 250 MHz (PCLK + phase delay)
            p_CLKOUT2_DIVIDE       = 4,
            p_CLKOUT2_PHASE        = 90.0,
            o_CLKOUT2              = ClockSignal("ss_io_shifted"),
        )


        # Grab our main clock.
        clk200 = platform.request(platform.default_clk).i

        # Create our I/O delay compensation unit.
        m.submodules.idelayctrl = Instance("IDELAYCTRL",
            i_REFCLK = clk200,
            i_RST    = ~usb3_locked
        )

        # Connect up our clock domains.
        m.d.comb += [
            # Synthetic clock domains.
            ClockSignal("sync")           .eq(clk200),
            ClockSignal("fast")           .eq(ClockSignal("ss_io")),
            ResetSignal("fast")           .eq(~usb3_locked),

            # USB2 resets
            ResetSignal("usb")            .eq(~usb2_locked),
            ResetSignal("usb_io")         .eq(phy_reset.phy_reset),

            # USB3 resets
            ResetSignal("ss")             .eq(~usb3_locked),
            ResetSignal("ss_io")          .eq(~usb3_locked),
            ResetSignal("ss_shifted")     .eq(~usb3_locked),
            ResetSignal("ss_io_shifted")  .eq(~usb3_locked),
        ]

        return m


class NexysVideoAB07SuperspeedPHY(GearedPIPEInterface):
    """ Interface for the TUSB1310A, mounted on the AB07 FMC board. """

    VADJ_VOLTAGE = '2.5V'

    def __init__(self, platform):
        logging.info("Using DesignGateway AB07 PHY board, connected via FMC.")

        # Grab the geared I/O for our PIPE PHY...
        phy_connection = platform.request('ab07_usbfmc_pipe', xdr=GearedPIPEInterface.GEARING_XDR)

        # ... and create a PIPE interface around it.
        super().__init__(pipe=phy_connection, invert_rx_polarity_signal=True)


    def elaborate(self, platform):

        # Grab our platform, and make an important tweak before returning it:
        m = super().elaborate(platform)

        # Ensure that we're driving VADJ with the proper I/O voltage.
        m.d.comb += [
            platform.request("vadj_select").eq(platform.VADJ_VALUES[self.VADJ_VOLTAGE])
        ]

        return m



class Genesys2Platform(_CoreGenesys2Platform, LUNAPlatform):
    """ Board description for the Digilent Genesys 2."""

    name                   = "Genesys2"
    default_usb_connection = "usb"
    ulpi_raw_clock_domain  = "usb_io"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = Genesys2ClockDomainGenerator

    # Temporary fix until upstream fixes their Genesys2 definition.
    def bank15_16_17_iostandard(self):
        return "LVCMOS" + self._JP6.replace('V', '')


    # Temporary resource collection that exist until an upstream fix is made.
    # Applied selectively only if nmigen_boards doesn't yet have the fix.
    temporary_resources = [
        ULPIResource(0, data="AE14 AE15 AC15 AC16 AB15 AA15 AD14 AC14",
            rst="AB14", clk="AD18", dir="Y16", stp="AA17", nxt="AA16",
            clk_dir="i", rst_invert=True, attrs=Attrs(IOSTANDARD="LVCMOS18"))
    ]


    def __init__(self, JP6="1V8"):
        logging.info(f"This platform requires you to set a VADJ jumper. You can either set it to {JP6},")
        logging.info("or adjust the invocation of the platform file to select another setting.")

        super().__init__(JP6)

        # Ensure that we have a fixed USB connection implementation; and if we don't, add it.
        try:
            self.lookup("usb", 0)
        except ResourceError:
            self.add_resources(self.temporary_resources)



