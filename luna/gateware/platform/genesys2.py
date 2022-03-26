#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Digilent Genesys2 Platform

This is an unsupported platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.genesys2:Genesys2Platform"

This platform has no built-in USB3 resources; but has a FMC that can be used to connect up
TUSB1310A PHYs, which offer ULPI USB2 and PIPE USB3. A ULPI PHY is provided on-board for USB2;
it is labeled "OTG on the relevant board."
"""

import os
import logging

from amaranth import *
from amaranth.build import *
from amaranth.vendor.xilinx_7series import Xilinx7SeriesPlatform

from amaranth_boards.genesys2 import Genesys2Platform as _CoreGenesys2Platform
from amaranth_boards.resources import *

from ..architecture.car     import PHYResetController
from ..interface.pipe       import GearedPIPEInterface, AsyncPIPEInterface
from ..interface.serdes_phy import XC7GTXSerDesPIPE

from .core import LUNAPlatform


class Genesys2HTGClockDomainGenerator(Elaboratable):
    """ Clock/Reset Controller for the Genesys2, used with TUSB1310 PHY. """

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
            p_CLKOUT0_PHASE        = 90,
            o_CLKOUT0              = ClockSignal("ss"),

            # CLKOUT1 = 125 MHz / 8ns (1/2 PCLK + phase delay)
            # We want to sample our input after 2ns. This is >=90 degrees of this clock.
            p_CLKOUT1_DIVIDE       = 8,
            p_CLKOUT1_PHASE        = 0.0,
            o_CLKOUT1              = ClockSignal("ss_shifted"),

            # CLKOUT2 = 250 MHz (PCLK + phase delay)
            p_CLKOUT2_DIVIDE       = 4,
            p_CLKOUT2_PHASE        = 90,
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

        # Convenience function: if we know we're going to be doing something low-power,
        # we can silence the FPGA fan. This is Mostly Harmless, since we have an internal
        # overtemperature shut-down anyway.
        if os.getenv('LUNA_SILENCE_FAN'):
            m.d.comb += platform.request("fan").pwm.o.eq(0)


        return m


class Genesys2HTGSuperSpeedPHY(GearedPIPEInterface):
    """ Interface for the TUSB1310A, mounted on the HTG-FMC-USB3.0 board. """

    SYNC_FREQUENCY = 200e6

    def __init__(self, platform, with_usb2=False, index=1):
        logging.info("Using the HiTechGlobal HTG-FMC-USB3.0 PHY board, connected via FMC.")

        self._with_usb2 = with_usb2
        self._index     = index

        # Grab the geared I/O for our PIPE PHY...
        phy_connection = platform.request('hitech_fmc_pipe', 1, xdr=GearedPIPEInterface.GEARING_XDR)

        # ... and create a PIPE interface around it.
        super().__init__(pipe=phy_connection)


    def elaborate(self, platform):

        # Grab our platform, so we can tweak it.
        m = super().elaborate(platform)

        # If we're not using the USB2 functionality, we'll want to drive the ULPI lines as straps.
        # Request them, so our PULL attributes are included.
        if not self._with_usb2:
            platform.request("hitech_fmc_ulpi_straps", 1)

        return m


class Genesys2GTXClockDomainGenerator(Elaboratable):
    """ Clock/Reset Controller for the Genesys2, used with the SerDes PHY. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Grab our main clock and reset.
        clk200 = platform.request(platform.default_clk).i
        rst    = platform.request(platform.default_rst).i

        # Create our domains; but don't do anything else for them, for now.
        m.domains.usb     = cd_usb      = ClockDomain()
        m.domains.usb_io  = cd_usb_io   = ClockDomain()
        m.domains.sync    = cd_sync     = ClockDomain()
        m.domains.ss      = cd_ss       = ClockDomain()
        m.domains.fast    = cd_fast     = ClockDomain()

        # USB2 connections.
        # To meet our PHY's timing, we'll need to shift the USB clock's phase a bit,
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
            i_RST                  = rst,
        )

        # USB3 PLL connections.
        clk250        = Signal()
        clk125        = Signal()
        usb3_locked   = Signal()
        usb3_feedback = Signal()
        m.submodules.usb3_pll = Instance("PLLE2_ADV",
            p_BANDWIDTH            = "OPTIMIZED",
            p_COMPENSATION         = "ZHOLD",
            p_STARTUP_WAIT         = "FALSE",
            p_DIVCLK_DIVIDE        = 1,
            p_CLKFBOUT_MULT        = 5,     # VCO = 1000 MHz
            p_CLKFBOUT_PHASE       = 0.000,
            p_CLKOUT0_DIVIDE       = 4,     # CLKOUT0 = 250 MHz (1000/4)
            p_CLKOUT0_PHASE        = 0.000,
            p_CLKOUT0_DUTY_CYCLE   = 0.500,
            p_CLKOUT1_DIVIDE       = 8,     # CLKOUT1 = 125 MHz (1000/8)
            p_CLKOUT1_PHASE        = 0.000,
            p_CLKOUT1_DUTY_CYCLE   = 0.500,
            i_CLKFBIN              = usb3_feedback,
            o_CLKFBOUT             = usb3_feedback,
            i_CLKIN1               = clk200,
            p_CLKIN1_PERIOD        = 20.000,
            o_CLKOUT0              = clk250,
            o_CLKOUT1              = clk125,
            o_LOCKED               = usb3_locked,
            i_RST                  = rst,
        )

        # Connect up our clock domains.
        m.d.comb += [
            ClockSignal("sync")     .eq(clk125),
            ClockSignal("ss")       .eq(clk125),
            ClockSignal("fast")     .eq(clk250),

            ResetSignal("usb")      .eq(~usb2_locked),
            ResetSignal("sync")     .eq(~usb3_locked),
            ResetSignal("ss")       .eq(~usb3_locked),
            ResetSignal("fast")     .eq(~usb3_locked),
        ]

        return m


class Genesys2GTXSuperSpeedPHY(AsyncPIPEInterface):
    """ Superspeed PHY configuration for the Genesys2, using transceivers. """

    SS_FREQUENCY   = 125e6
    FAST_FREQUENCY = 250e6


    def __init__(self, platform):

        # Grab the I/O that implements our SerDes interface...
        serdes_io = platform.request("hitech_fmc_serdes", dir={'tx':"-", 'rx':"-"})

        # Use it to create our soft PHY...
        serdes_phy = XC7GTXSerDesPIPE(
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



class Genesys2Platform(_CoreGenesys2Platform, LUNAPlatform):
    """ Board description for the Digilent Genesys 2."""

    name                   = "Genesys2"
    default_usb_connection = "usb"
    ulpi_raw_clock_domain  = "usb_io"

    # Select how we'll connect to our USB PHY.
    usb_connections = 'hpc_fmc'

    if usb_connections == 'hpc_fmc':
        clock_domain_generator = Genesys2HTGClockDomainGenerator
        default_usb3_phy       = Genesys2HTGSuperSpeedPHY
    else:
        clock_domain_generator = Genesys2GTXClockDomainGenerator
        default_usb3_phy       = Genesys2GTXSuperSpeedPHY


    # Additional resources for LUNA-specific connections.
    additional_resources = [

        # HiTech Global FMC_USB3 board connections (USB2 and USB3).
        # !!! WARNING !!! VADJ (JP6) must be set to 1.8V before this board can be used!
        #
        # Link: <http://www.hitechglobal.com/FMCModules/FMC_USB3.htm>

        #
        # PHY P2; the micro-B connector that's farther away from others.
        #
        Resource("hitech_fmc_pipe", 2,
            # Transmit bus.
            Subsignal("tx_clk",  Pins("fmc_0:hb10_p", dir="o")),
            Subsignal("tx_data", Pins(
                "fmc_0:hb05_p "     # DATA0
                "fmc_0:hb09_n "     # DATA1
                "fmc_0:hb05_n "     # DATA2
                "fmc_0:hb08_n "     # DATA3
                "fmc_0:hb03_n "     # DATA4
                "fmc_0:hb04_n "     # DATA5
                "fmc_0:hb03_p "     # DATA6
                "fmc_0:hb02_p "     # DATA7
                "fmc_0:hb04_p "     # DATA8
                "fmc_0:hb02_n "     # DATA9
                "fmc_0:hb08_p "     # DATA10
                "fmc_0:hb09_p "     # DATA11
                "fmc_0:hb06_n "     # DATA12
                "fmc_0:hb07_p "     # DATA13
                "fmc_0:hb06_p "     # DATA14
                "fmc_0:hb01_n",     # DATA15
                dir="o"
                )
            ),
            Subsignal("tx_datak", Pins("fmc_0:hb07_n fmc_0:hb01_p", dir="o")),

            # Transmit configuration.
            Subsignal("tx_oneszeros",  Pins("fmc_0:hb13_p",                           dir="o")),
            Subsignal("tx_deemph",     Pins("fmc_0:hb14_p fmc_0:hb19_p",              dir="o")),
            Subsignal("tx_margin",     Pins("fmc_0:hb19_n fmc_0:hb15_n fmc_0:hb21_p", dir="o")), # note
            Subsignal("tx_swing",      Pins("fmc_0:hb10_n",                           dir="o")), # note
            Subsignal("tx_detrx_lpbk", Pins("fmc_0:hb13_n",                           dir="o")),
            Subsignal("tx_elecidle",   Pins("fmc_0:hb11_n", dir="o"), Attrs(PULLUP="True")    ),

            # Receive bus.
            Subsignal("pclk",   Pins("fmc_0:ha00_p", dir="i"), Clock(250e6)),
            Subsignal("rx_valid", Pins("fmc_0:ha10_n",  dir="i")),
            Subsignal("rx_data",  Pins(
                "fmc_0:ha11_p "  #DATA0
                "fmc_0:ha06_n "  #DATA1
                "fmc_0:ha10_p "  #DATA2
                "fmc_0:ha08_n "  #DATA3
                "fmc_0:ha07_n "  #DATA4
                "fmc_0:ha09_n "  #DATA5
                "fmc_0:ha08_p "  #DATA6
                "fmc_0:ha07_p "  #DATA7
                "fmc_0:ha06_p "  #DATA8
                "fmc_0:ha04_n "  #DATA9
                "fmc_0:ha09_p "  #DATA10
                "fmc_0:ha02_n "  #DATA11
                "fmc_0:ha04_p "  #DATA12
                "fmc_0:ha02_p "  #DATA13
                "fmc_0:ha05_p "  #DATA14
                "fmc_0:ha03_p ", #DATA15
                dir="i"
                )
            ),
            Subsignal("rx_datak", Pins("fmc_0:ha05_n fmc_0:ha03_n", dir="i")),

            # Receive status signals.
            Subsignal("rx_polarity",    Pins("fmc_0:hb18_n",                                 dir="o")),
            Subsignal("rx_termination", Pins("fmc_0:hb12_n",                                 dir="o")),
            Subsignal("rx_elecidle",    Pins("fmc_0:hb16_p",                                 dir="i")),
            Subsignal("rx_status",      Pins("fmc_0:hb12_p fmc_0:hb17_n fmc_0:hb17_p", dir="i" )),

            # Full-PHY Control and status.
            Subsignal("reset",         PinsN("fmc_0:hb21_n",              dir="o" )),
            Subsignal("phy_reset",     PinsN("fmc_0:hb11_p",              dir="o" )),
            Subsignal("power_down",    Pins( "fmc_0:hb20_p fmc_0:hb20_n", dir="o" )),
            Subsignal("rate",          Pins( "fmc_0:hb15_p",              dir="o" )),
            Subsignal("elas_buf_mode", Pins( "fmc_0:hb18_p",              dir="o" )),
            Subsignal("phy_status",    Pins( "fmc_0:hb16_n",              dir="i")),
            Subsignal("power_present", Pins( "fmc_0:hb14_n",              dir="i" )),

            Attrs(IOSTANDARD="LVCMOS18")
        ),

        ULPIResource("hitech_fmc_ulpi", 2, clk="fmc_0:ha17_p",
            dir="fmc_0:ha22_p", nxt="fmc_0:ha18_p", stp="fmc_0:ha21_p",
            data=
                "fmc_0:ha20_n "   # DATA0
                "fmc_0:ha20_p "   # DATA1
                "fmc_0:ha23_p "   # DATA2
                "fmc_0:ha18_n "   # DATA3
                "fmc_0:ha22_n "   # DATA4
                "fmc_0:ha19_n "   # DATA5
                "fmc_0:ha21_n "   # DATA6
                "fmc_0:ha19_p",   # DATA7
            attrs=Attrs(IOSTANDARD="LVCMOS18"),
        ),
        Resource("hitech_fmc_clkout", 2, Pins("fmc_0:hb00_p", dir="i"), Attrs(IOSTANDARD="LVCMOS18")),

        #
        # PHY P1; center micro-B connector.
        #
        Resource("hitech_fmc_pipe", 1,
            # Transmit bus.
            Subsignal("tx_clk",  Pins("fmc_0:la20_p", dir="o")),
            Subsignal("tx_data", Pins(
                "fmc_0:la24_n "     # DATA0
                "fmc_0:la26_n "     # DATA1
                "fmc_0:la24_p "     # DATA2
                "fmc_0:la26_p "     # DATA3
                "fmc_0:la25_n "     # DATA4
                "fmc_0:la21_n "     # DATA5
                "fmc_0:la25_p "     # DATA6
                "fmc_0:la21_p "     # DATA7
                "fmc_0:la22_p "     # DATA8
                "fmc_0:la22_n "     # DATA9
                "fmc_0:la19_n "     # DATA10
                "fmc_0:la23_n "     # DATA11
                "fmc_0:la23_p "     # DATA12
                "fmc_0:la18_p "     # DATA13
                "fmc_0:la19_p "     # DATA14
                "fmc_0:la20_n",     # DATA15
                dir="o"
                )
            ),
            Subsignal("tx_datak", Pins("fmc_0:la18_n fmc_0:la17_p", dir="o")),

            # Transmit configuration.
            Subsignal("tx_oneszeros",  Pins("fmc_0:la27_n",              dir="o")), # note
            Subsignal("tx_deemph",     Pins("fmc_0:la31_p fmc_0:la28_n", dir="o")),
            Subsignal("tx_margin",     Pins("fmc_0:la31_n fmc_0:la30_p fmc_0:la30_n", dir="o")), # note
            Subsignal("tx_swing",      Pins("fmc_0:la29_p",              dir="o")), # note
            Subsignal("tx_detrx_lpbk", Pins("fmc_0:la29_n",              dir="o")),
            Subsignal("tx_elecidle",   Pins("fmc_0:la27_p",              dir="o")),

            # Receive bus.
            Subsignal("pclk",   Pins("fmc_0:la01_p", dir="i"), Clock(250e6)),
            Subsignal("rx_valid", Pins("fmc_0:la11_p",  dir="i")),
            Subsignal("rx_data",  Pins(
                "fmc_0:la10_n "  #DATA0
                "fmc_0:la10_p "  #DATA1
                "fmc_0:la09_n "  #DATA2
                "fmc_0:la09_p "  #DATA3
                "fmc_0:la07_n "  #DATA4
                "fmc_0:la08_n "  #DATA5
                "fmc_0:la05_n "  #DATA6
                "fmc_0:la03_n "  #DATA7
                "fmc_0:la06_n "  #DATA8
                "fmc_0:la02_p "  #DATA9
                "fmc_0:la06_p "  #DATA10
                "fmc_0:la04_p "  #DATA11
                "fmc_0:la03_p "  #DATA12
                "fmc_0:la08_p "  #DATA13
                "fmc_0:la07_p "  #DATA14
                "fmc_0:la04_n ", #DATA15
                dir="i"
                )
            ),
            Subsignal("rx_datak", Pins("fmc_0:la02_n fmc_0:la05_p", dir="i")),

            # Receive status signals.
            Subsignal("rx_polarity",    Pins("fmc_0:la16_n",                           dir="o")),
            Subsignal("rx_termination", Pins("fmc_0:la13_n",                           dir="o")),
            Subsignal("rx_elecidle",    Pins("fmc_0:la11_n",                           dir="i")),
            Subsignal("rx_status",      Pins("fmc_0:la14_p fmc_0:la15_p fmc_0:la14_n", dir="i")),

            # Full-PHY Control and status.
            Subsignal("reset",         PinsN("fmc_0:la32_n",              dir="o" )),
            Subsignal("phy_reset",     PinsN("fmc_0:la12_p",              dir="o" )),
            Subsignal("power_down",    Pins( "fmc_0:la12_n fmc_0:la13_p", dir="o" )),
            Subsignal("rate",          Pins( "fmc_0:la28_p",              dir="o" )),
            Subsignal("elas_buf_mode", Pins( "fmc_0:la15_n",              dir="o" )),
            Subsignal("phy_status",    Pins( "fmc_0:la16_p",              dir="i")),
            Subsignal("power_present", Pins( "fmc_0:la32_p",              dir="i" )),

            Attrs(IOSTANDARD="LVCMOS18")
        ),

        ULPIResource("hitech_fmc_ulpi", 1, clk="fmc_0:ha01_p",
            dir="fmc_0:ha14_p", nxt="fmc_0:ha13_p", stp="fmc_0:ha16_n",
            data=
                "fmc_0:ha11_n "   # DATA0
                "fmc_0:ha13_n "   # DATA1
                "fmc_0:ha15_n "   # DATA2
                "fmc_0:ha12_n "   # DATA3
                "fmc_0:ha14_n "   # DATA4
                "fmc_0:ha15_p "   # DATA5
                "fmc_0:ha16_p "   # DATA6
                "fmc_0:ha12_p",   # DATA7
            attrs=Attrs(IOSTANDARD="LVCMOS18"),
        ),

        # ULPI straps; for use only if we don't request the ULPI resource.
        Resource("hitech_fmc_ulpi_straps", 1,
            Subsignal("iso_start_strap",  Pins("fmc_0:ha12_p"), Attrs(PULLDOWN="TRUE")),
            Subsignal("ulpi_8bit_strap",  Pins("fmc_0:ha16_p"), Attrs(PULLDOWN="TRUE")),
            Subsignal("refclksel1_strap", Pins("fmc_0:ha15_p"), Attrs(PULLUP="TRUE"  )),
            Subsignal("refclksel0_strap", Pins("fmc_0:ha14_p"), Attrs(PULLUP="TRUE"  )),
            Attrs(IOSTANDARD="LVCMOS18")
        ),

        Resource("hitech_fmc_clkout", 1, Pins("fmc_0:la00_p", dir="i"), Attrs(IOSTANDARD="LVCMOS18")),

        #
        # PHY P3; outer of the two close-together micro-B ports.
        #
        Resource("hitech_fmc_serdes", 0,
            Subsignal("tx", DiffPairs("fmc_0:dp0_c2m_p", "fmc_0:dp0_c2m_n")),
            Subsignal("rx", DiffPairs("fmc_0:dp0_m2c_p", "fmc_0:dp0_m2c_n")),
        ),

        # Convenience: user_io.
        Resource("user_io", 0, Pins("U27"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 1, Pins("U28"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 2, Pins("T26"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 3, Pins("T27"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 4, Pins("T22"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 5, Pins("T23"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 6, Pins("T20"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 7, Pins("T21"), Attrs(IOSTANDARD="LVCMOS33")),
    ]

    additional_connectors = [
        Connector("fmc", 0, {
            "clk_dir": "ab30",
            "clk0_m2c_n": "e20",
            "clk0_m2c_p": "f20",
            "clk1_m2c_n": "d28",
            "clk1_m2c_p": "e28",
            "clk2_n": "k25",
            "clk2_p": "l25",
            "dp0_c2m_p": "y2",
            "dp0_c2m_n": "y1",
            "dp0_m2c_p": "aa4",
            "dp0_m2c_n": "aa3",
            "ha00_n": "k29",
            "ha00_p": "k28",
            "ha01_n": "l28",
            "ha01_p": "m28",
            "ha02_n": "p22",
            "ha02_p": "p21",
            "ha03_n": "n26",
            "ha03_p": "n25",
            "ha04_n": "m25",
            "ha04_p": "m24",
            "ha05_n": "h29",
            "ha05_p": "j29",
            "ha06_n": "n30",
            "ha06_p": "n29",
            "ha07_n": "m30",
            "ha07_p": "m29",
            "ha08_n": "j28",
            "ha08_p": "j27",
            "ha09_n": "k30",
            "ha09_p": "l30",
            "ha10_n": "n22",
            "ha10_p": "n21",
            "ha11_n": "n24",
            "ha11_p": "p23",
            "ha12_n": "l27",
            "ha12_p": "l26",
            "ha13_n": "j26",
            "ha13_p": "k26",
            "ha14_n": "m27",
            "ha14_p": "n27",
            "ha15_n": "j22",
            "ha15_p": "j21",
            "ha16_n": "m23",
            "ha16_p": "m22",
            "ha17_n": "b25",
            "ha17_p": "c25",
            "ha18_n": "d19",
            "ha18_p": "e19",
            "ha19_n": "f30",
            "ha19_p": "g29",
            "ha20_n": "f27",
            "ha20_p": "g27",
            "ha21_n": "f28",
            "ha21_p": "g28",
            "ha22_n": "c21",
            "ha22_p": "d21",
            "ha23_n": "f18",
            "ha23_p": "g18",
            "hb00_n": "f13",
            "hb00_p": "g13",
            "hb01_n": "g15",
            "hb01_p": "h15",
            "hb02_n": "k15",
            "hb02_p": "l15",
            "hb03_n": "g14",
            "hb03_p": "h14",
            "hb04_n": "h16",
            "hb04_p": "j16",
            "hb05_n": "k16",
            "hb05_p": "l16",
            "hb06_n": "e13",
            "hb06_p": "f12",
            "hb07_n": "a13",
            "hb07_p": "b13",
            "hb08_n": "j14",
            "hb08_p": "k14",
            "hb09_n": "b15",
            "hb09_p": "c15",
            "hb10_n": "j12",
            "hb10_p": "j11",
            "hb11_n": "c11",
            "hb11_p": "d11",
            "hb12_n": "a12",
            "hb12_p": "a11",
            "hb13_n": "b12",
            "hb13_p": "c12",
            "hb14_n": "h12",
            "hb14_p": "h11",
            "hb15_n": "l13",
            "hb15_p": "l12",
            "hb16_n": "j13",
            "hb16_p": "k13",
            "hb17_n": "d13",
            "hb17_p": "d12",
            "hb18_n": "e15",
            "hb18_p": "e14",
            "hb19_n": "e11",
            "hb19_p": "f11",
            "hb20_n": "a15",
            "hb20_p": "b14",
            "hb21_n": "c14",
            "hb21_p": "d14",
            "la00_n": "c27",
            "la00_p": "d27",
            "la01_n": "c26",
            "la01_p": "d26",
            "la02_n": "g30",
            "la02_p": "h30",
            "la03_n": "e30",
            "la03_p": "e29",
            "la04_n": "h27",
            "la04_p": "h26",
            "la05_n": "a30",
            "la05_p": "b30",
            "la06_n": "c30",
            "la06_p": "d29",
            "la07_n": "e25",
            "la07_p": "f25",
            "la08_n": "b29",
            "la08_p": "c29",
            "la09_n": "a28",
            "la09_p": "b28",
            "la10_n": "a27",
            "la10_p": "b27",
            "la11_n": "a26",
            "la11_p": "a25",
            "la12_n": "e26",
            "la12_p": "f26",
            "la13_n": "d24",
            "la13_p": "e24",
            "la14_n": "b24",
            "la14_p": "c24",
            "la15_n": "a23",
            "la15_p": "b23",
            "la16_n": "d23",
            "la16_p": "e23",
            "la17_n": "e21",
            "la17_p": "f21",
            "la18_n": "d18",
            "la18_p": "d17",
            "la19_n": "h22",
            "la19_p": "h21",
            "la20_n": "f22",
            "la20_p": "g22",
            "la21_n": "l18",
            "la21_p": "l17",
            "la22_n": "h17",
            "la22_p": "j17",
            "la23_n": "f17",
            "la23_p": "g17",
            "la24_n": "g20",
            "la24_p": "h20",
            "la25_n": "c22",
            "la25_p": "d22",
            "la26_n": "a22",
            "la26_p": "b22",
            "la27_n": "a21",
            "la27_p": "a20",
            "la28_n": "h19",
            "la28_p": "j19",
            "la29_n": "a18",
            "la29_p": "b18",
            "la30_n": "a17",
            "la30_p": "a16",
            "la31_n": "b17",
            "la31_p": "c17",
            "la32_n": "j18",
            "la32_p": "k18",
            "la33_n": "c16",
            "la33_p": "d16",
            "scl": "ac24",
            "sda": "ad24",
        })

    ]


    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            "script_after_read": "auto_detect_xpm",
            "script_before_bitstream": "set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]",
            "add_constraints": """
                set_property CFGBVS VCCO [current_design]
                set_property CONFIG_VOLTAGE 3.3 [current_design]

                # Allow the USB2 PLL to exist even if ``usb_io`` isn't driven.
                # This saves us having to customize our logic if the USB2 domains aren't used.
                set_property SEVERITY {Warning} [get_drc_checks REQP-161]
            """}
        return Xilinx7SeriesPlatform.toolchain_prepare(self, fragment, name, **overrides, **kwargs)



    def __init__(self, JP6="1V8"):
        logging.info(f"This platform requires you to set a VADJ jumper. You can either set it to {JP6},")
        logging.info("or adjust the invocation of the platform file to select another setting.")

        super().__init__(JP6)

        # Add our additional resources.
        self.add_resources(self.additional_resources)
        self.add_connectors(self.additional_connectors)



