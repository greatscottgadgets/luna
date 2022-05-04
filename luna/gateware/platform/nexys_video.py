#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Digilent Nexys Video Platform Files

This is an unsupported platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.nexys_video:NexysVideoPlatform"

This platform has no built-in USB resources; but has a FMC that can be used to connect up
TUSB1310A PHYs, which offer ULPI USB2 and PIPE USB3. They also have pmods, which can be
connected up via our gateware PHY.
"""

import os
import logging
import subprocess

from amaranth import *
from amaranth.build import *
from amaranth.vendor.xilinx_7series import Xilinx7SeriesPlatform

from amaranth_boards.resources import *
from ..interface.pipe import GearedPIPEInterface

from .core import LUNAPlatform


class NexysVideoClockDomainGenerator(Elaboratable):
    """ Clock/Reset Controller for the Nexys Video. """

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

        # Grab our main clock.
        clk100 = platform.request(platform.default_clk)

        # USB2 PLL connections.
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
            p_CLKIN1_PERIOD        = 20.000,
            i_CLKFBIN              = usb2_feedback,
            o_CLKFBOUT             = usb2_feedback,
            i_CLKIN1               = clk100,
            o_CLKOUT0              = ClockSignal("usb"),
            o_CLKOUT1              = ClockSignal("usb_io"),
            o_LOCKED               = usb2_locked,
        )

        clk_idelay         = Signal()

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
            p_CLKOUT2_PHASE        = 00.0,
            o_CLKOUT2              = ClockSignal("ss_io_shifted"),

            # CLKOUT3 = 200 MHz (for our the chip's I/O delay equalization)
            p_CLKOUT3_DIVIDE       = 5,
            p_CLKOUT3_PHASE        = 0.0,
            o_CLKOUT3              = clk_idelay
        )

        # Create our I/O delay compensation unit.
        m.submodules.idelayctrl = Instance("IDELAYCTRL",
            i_REFCLK = clk_idelay,
            i_RST    = ~usb3_locked
        )

        # Connect up our clock domains.
        m.d.comb += [
            # Synthetic clock domains.
            ClockSignal("sync")           .eq(clk100),
            ClockSignal("fast")           .eq(ClockSignal("ss_io")),
            ResetSignal("fast")           .eq(~usb3_locked),

            # USB2 resets
            ResetSignal("usb")            .eq(~usb2_locked),
            ResetSignal("usb_io")         .eq(~usb2_locked),

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



class NexysVideoPlatform(Xilinx7SeriesPlatform, LUNAPlatform):
    """ Board description for the Nexys Video. """

    name        = "Nexys Video"

    device      = "xc7a200t"
    package     = "sbg484"
    speed       = "1"

    default_clk = "clk100"
    default_rst = "cpu_reset"


    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = NexysVideoClockDomainGenerator


    # Select how we'll connect to our USB PHY.
    usb_connections = 'ab07_fmcusb'

    if usb_connections == 'ab07_fmcusb':
        default_usb_connection = "usb"
        default_usb3_phy       = NexysVideoAB07SuperspeedPHY


    VADJ_VALUES = {
        '1.2V': 0b00,
        '1.8V': 0b01,
        '2.5V': 0b10,
        '3.3V': 0b11
    }

    #
    # I/O resources.
    #

    resources = [
        # Clock / reset.
        Resource("clk100", 0, Pins("R4"), Attrs(IOSTANDARD="LVCMOS33"), Clock(100e6)),
        Resource("cpu_reset", 0, PinsN("G4"), Attrs(IOSTANDARD="LVCMOS15")),

        # Simple I/O
        *LEDResources(pins="T14 T15 T16 U16 V15 W16 W15 Y13", attrs=Attrs(IOSTANDARD="LVCMOS25")),
        *SwitchResources(pins="E22 F21 G21 G22 H17 J16 K13 M17", attrs=Attrs(IOSTANDARD="LVCMOS25")),
        *ButtonResources(pins="B22 D22 C12 D14 F15 G4", attrs=Attrs(IOSTANDARD="LVCMOS25")),

        # Adjustable voltage select
        Resource("vadj_select", 0, Pins("AA13 AB17", dir="o"), Attrs(IOSTANDARD="LVCMOS25")),

        # OLED screen
        Resource("oled", 0,
            Subsignal("dc",   Pins("W22")),
            Subsignal("res",  Pins("U21")),
            Subsignal("sclk", Pins("W21")),
            Subsignal("sdin", Pins("Y22")),
            Subsignal("vbat", Pins("P20")),
            Subsignal("vdd",  Pins("V22")),
            Attrs(IOSTANDARD="LVCMOS33")
        ),

        # PC comms
        UARTResource(0, tx="AA19", rx="V18", attrs=Attrs(IOSTANDARD="LVCMOS33")),

        Resource("usb_fifo", 0,
            Subsignal("data",  Pins("U20 P14 P15 U17 R17 P16 R18 N14")),
            Subsignal("rxf_n", Pins("N17")),
            Subsignal("txe_n", Pins("Y19")),
            Subsignal("rd_n",  Pins("P19")),
            Subsignal("wr_n",  Pins("R19")),
            Subsignal("siwua", Pins("P17")),
            Subsignal("oe_n",  Pins("V17")),
            Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST", DRIVE="8")
        ),

        #
        # USB connection options.
        #
        # The Nexys Video has no user-accessible USB2/3, so we rely on FMC-connected USB3 PHYs,
        # and PMOD connected USB2 PHYs. This is actually fairly valuable as a reference platform,
        # since the number of publicly-available boards with PIPE PHYs is very low.
        #

        # AB07-USBFMC board connections (USB3 only).
        # !!! WARNING !!! VADJ must be set to 2.5V before this board can be used!
        #
        # Link: <https://www.mouser.com/ProductDetail/Design-Gateway/AB07-USB3FMC?qs=5aG0NVq1C4wWGaHs8Oqcww%3D%3D>
        #
        Resource("ab07_usbfmc_pipe", 0,
            # Transmit bus.
            Subsignal("tx_clk",  Pins("FMC_0:LA11_P", dir="o")),
            Subsignal("tx_data", Pins(
                "FMC_0:LA00_CC_P "  # DATA0
                "FMC_0:LA02_P "     # DATA1
                "FMC_0:LA01_CC_P "  # DATA2
                "FMC_0:LA03_P "     # DATA3
                "FMC_0:LA06_P "     # DATA4
                "FMC_0:LA05_P "     # DATA5
                "FMC_0:LA08_P "     # DATA6
                "FMC_0:LA07_P "     # DATA7
                "FMC_0:LA10_P "     # DATA8
                "FMC_0:LA09_P "     # DATA9
                "FMC_0:LA12_P "     # DATA10
                "FMC_0:LA04_P "     # DATA11
                "FMC_0:LA16_P "     # DATA12
                "FMC_0:LA13_P "     # DATA13
                "FMC_0:LA15_P "     # DATA14
                "FMC_0:LA14_P ",    # DATA15
                dir="o"
                )
            ),
            Subsignal("tx_datak", Pins("FMC_0:LA16_N FMC_0:LA15_N", dir="o")),

            # Transmit config.
            Subsignal("tx_elecidle",    Pins("FMC_0:LA09_N",                 dir="o" )),
            Subsignal("tx_detrx_lpbk",  Pins("FMC_0:LA00_CC_N",              dir="o" )),
            Subsignal("tx_deemph",      Pins("FMC_0:LA01_CC_N FMC_0:LA05_N", dir="o" )),
            Subsignal("tx_margin",      Pins("FMC_0:LA03_N ",                dir="o" )),

            # Receive bus.
            Subsignal("pclk",     Pins("FMC_0:LA17_CC_P", dir="i"), Clock(250e6)),
            Subsignal("rx_valid", Pins("FMC_0:LA20_N",    dir="i" )),
            Subsignal("rx_data",  Pins(
                "FMC_0:LA19_P "     # DATA0
                "FMC_0:LA22_P "     # DATA1
                "FMC_0:LA20_P "     # DATA2
                "FMC_0:LA21_P "     # DATA3
                "FMC_0:LA18_CC_P "  # DATA4
                "FMC_0:LA23_P "     # DATA5
                "FMC_0:LA25_P "     # DATA6
                "FMC_0:LA26_P "     # DATA7
                "FMC_0:LA24_P "     # DATA8
                "FMC_0:LA29_P "     # DATA9
                "FMC_0:LA27_P "     # DATA10
                "FMC_0:LA28_P "     # DATA11
                "FMC_0:LA31_P "     # DATA12
                "FMC_0:LA30_P "     # DATA13
                "FMC_0:LA32_P "     # DATA14
                "FMC_0:LA33_P ",    # DATA15
                dir="i"
                )
            ),
            Subsignal("rx_datak",      Pins("FMC_0:LA28_N FMC_0:LA29_N", dir="i")),

            # Receive status/config.
            Subsignal("rx_status",      Pins("FMC_0:LA22_N FMC_0:LA25_N FMC_0:LA23_N", dir="i" )),
            Subsignal("rx_elecidle",    Pins("FMC_0:LA10_N",            dir="io")),
            Subsignal("rx_polarity",    Pins("FMC_0:LA24_N",            dir="o" )),
            Subsignal("rx_termination", Pins("FMC_0:LA18_CC_N",         dir="o" )),

            # Full-PHY Control and status.
            Subsignal("reset",          PinsN("FMC_0:LA02_N",             dir="o" )),
            Subsignal("phy_reset",      PinsN("FMC_0:LA08_N",             dir="o" )),
            Subsignal("power_down",     Pins("FMC_0:LA07_N FMC_0:LA12_N", dir="o" )),
            Subsignal("phy_status",     Pins("FMC_0:LA21_N",              dir="i")),
            Subsignal("power_present",  Pins("FMC_0:LA31_N",              dir="i" )),
            Subsignal("out_enable",     Pins("FMC_0:LA04_N"  ,            dir="o" )),

            # Attributes
            Attrs(IOSTANDARD="LVCMOS25")
        ),


        # HiTech Global FMC_USB3 board connections (USB2 and USB3).
        # !!! WARNING !!! VADJ must be set to 1.8V before this board can be used!
        #
        # Link: <http://www.hitechglobal.com/FMCModules/FMC_USB3.htm>
        Resource("hitech_fmc_pipe", 0,
            # Transmit bus.
            Subsignal("tx_clk",  Pins("FMC_0:LA20_P", dir="o")),
            Subsignal("tx_data", Pins(
                "FMC_0:LA24_N  "    # DATA0
                "FMC_0:LA26_N  "    # DATA1
                "FMC_0:LA24_P  "    # DATA2
                "FMC_0:LA26_P  "    # DATA3
                "FMC_0:LA25_N  "    # DATA4
                "FMC_0:LA21_N  "    # DATA5
                "FMC_0:LA25_P  "    # DATA6
                "FMC_0:LA21_P  "    # DATA7
                "FMC_0:LA22_P  "    # DATA8
                "FMC_0:LA22_N  "    # DATA9
                "FMC_0:LA19_N  "    # DATA10
                "FMC_0:LA23_N  "    # DATA11
                "FMC_0:LA23_P  "    # DATA12
                "FMC_0:LA18_CC_P "  # DATA13
                "FMC_0:LA19_P "     # DATA14
                "FMC_0:LA20_N",     # DATA15
                dir="o"
                )
            ),
            Subsignal("tx_datak", Pins("FMC_0:LA18_CC_N FMC_0:LA17_CC_P", dir="o")),

            # Transmit configuration.
            Subsignal("tx_oneszeros",  Pins("FMC_0:LA27_N",            dir="o")),
            Subsignal("tx_deemph",     Pins("FMC_0:LA31_P FMC_0:LA28_N", dir="o")),
            Subsignal("tx_margin",     Pins("FMC_0:LA30_P FMC_0:LA30_N", dir="o")),
            Subsignal("tx_swing",      Pins("FMC_0:LA29_P",            dir="o")),
            Subsignal("tx_detrx_lpbk", Pins("FMC_0:LA29_N",            dir="o")),
            Subsignal("tx_elecidle",   Pins("FMC_0:LA27_P",            dir="o")),

            # Receive bus.
            Subsignal("rx_clk",   Pins("FMC_0:LA01_CC_P", dir="i"), Clock(250e6)),
            Subsignal("rx_valid", Pins("FMC_0:LA11_P",    dir="i")),
            Subsignal("rx_data",  Pins(
                "FMC_0:LA10_N "  #DATA0
                "FMC_0:LA10_P "  #DATA1
                "FMC_0:LA09_N "  #DATA2
                "FMC_0:LA09_P "  #DATA3
                "FMC_0:LA07_N "  #DATA4
                "FMC_0:LA08_N "  #DATA5
                "FMC_0:LA05_N "  #DATA6
                "FMC_0:LA03_N "  #DATA7
                "FMC_0:LA06_N "  #DATA8
                "FMC_0:LA02_P "  #DATA9
                "FMC_0:LA06_P "  #DATA10
                "FMC_0:LA04_P "  #DATA11
                "FMC_0:LA03_P "  #DATA12
                "FMC_0:LA08_P "  #DATA13
                "FMC_0:LA07_P "  #DATA14
                "FMC_0:LA04_N ", #DATA15
                dir="i"
                )
            ),
            Subsignal("rx_datak", Pins("FMC_0:LA02_N FMC_0:LA05_P", dir="i")),

            # Receive status signals.
            Subsignal("rx_polarity",    Pins("FMC_0:LA16_N",                           dir="i" )),
            Subsignal("rx_termination", Pins("FMC_0:LA13_N",                           dir="i" )),
            Subsignal("rx_elecidle",    Pins("FMC_0:LA11_N",                           dir="io")),
            Subsignal("rx_status",      Pins("FMC_0:LA14_P FMC_0:LA15_P FMC_0:LA14_N", dir="i" )),

            # Full-PHY Control and status.
            Subsignal("phy_reset",     PinsN("FMC_0:LA12_P",              dir="o" )),
            Subsignal("power_down",    Pins( "FMC_0:LA12_N FMC_0:LA13_P", dir="o" )),
            Subsignal("rate",          Pins( "FMC_0:LA28_P",              dir="o" )),
            Subsignal("elas_buf_mode", Pins( "FMC_0:LA15_N",              dir="o" )),
            Subsignal("phy_status",    Pins( "FMC_0:LA16_P",              dir="io")),
            Subsignal("pwr_present",   Pins( "FMC_0:LA32_P",              dir="i" )),
            Subsignal("reset",         PinsN("FMC_0:LA32_N",              dir="o" )),

            Attrs(IOSTANDARD="LVCMOS18")
        ),

        ULPIResource("hitech_fmc_ulpi", 0, clk="FMC_0:HA01_CC_P",
            dir="FMC_0:HA14_P", nxt="FMC_0:HA13_P", stp="FMC_0:HA16_N",
            data=
                "FMC_0:HA11_N "   # DATA0
                "FMC_0:HA13_N "   # DATA1
                "FMC_0:HA15_N "   # DATA2
                "FMC_0:HA12_N "   # DATA3
                "FMC_0:HA14_N "   # DATA4
                "FMC_0:HA15_P "   # DATA5
                "FMC_0:HA16_P "   # DATA6
                "FMC_0:HA12_P",   # DATA7
            attrs=Attrs(IOSTANDARD="LVCMOS18"),
        ),
        Resource("hitech_fmc_clkout", 0, Pins("FMC_0:LA00_CC_P", dir="i"), Attrs(IOSTANDARD="LVCMOS18")),

        # Example direct-USB connection.
        DirectUSBResource(0, d_p="JA_0:1", d_n="JA_0:2", pullup="JA_0:3", attrs=Attrs(IOSTANDARD="LVCMOS33")),

        # Convenience: User I/O
        Resource("user_io", 0, Pins("JB_0:1"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 1, Pins("JB_0:2"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 2, Pins("JB_0:3"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("user_io", 3, Pins("JB_0:4"), Attrs(IOSTANDARD="LVCMOS33"))
    ]

    #
    # Board I/O connectors.
    #
    connectors = [
        Connector("FMC", 0, {
            "DP0_C2M_P"     : "D7",
            "DP0_C2M_N"     : "C7",
            "DP0_M2C_P"     : "D9",
            "DP0_M2C_N"     : "C9",
            "GBTCLK0_M2C_P" : "F10",
            "GBTCLK0_M2C_N" : "E10",
            "LA01_CC_P"     : "J20",
            "LA01_CC_N"     : "J21",
            "LA05_P"        : "M21",
            "LA05_N"        : "L21",
            "LA09_P"        : "H20",
            "LA09_N"        : "G20",
            "LA13_P"        : "K17",
            "LA13_N"        : "J17",
            "LA17_CC_P"     : "B17",
            "LA17_CC_N"     : "B18",
            "LA23_P"        : "B21",
            "LA23_N"        : "A21",
            "LA26_P"        : "F18",
            "LA26_N"        : "E18",
            "CLK0_M2C_P"    : "J19",
            "CLK0_M2C_N"    : "A19",
            "LA02_P"        : "M18",
            "LA02_N"        : "L18",
            "LA04_P"        : "N20",
            "LA04_N"        : "M20",
            "LA07_P"        : "M13",
            "LA07_N"        : "L13",
            "LA11_P"        : "L14",
            "LA11_N"        : "L15",
            "LA15_P"        : "L16",
            "LA15_N"        : "K16",
            "LA19_P"        : "A18",
            "LA19_N"        : "A19",
            "LA21_P"        : "E19",
            "LA21_N"        : "D19",
            "LA24_P"        : "B15",
            "LA24_N"        : "B16",
            "LA28_P"        : "C13",
            "LA28_N"        : "B13",
            "LA30_P"        : "A13",
            "LA30_N"        : "A14",
            "LA32_P"        : "A15",
            "LA32_N"        : "A16",
            "LA06_P"        : "N22",
            "LA06_N"        : "M22",
            "LA10_P"        : "K21",
            "LA10_N"        : "K22",
            "LA14_P"        : "J22",
            "LA14_N"        : "H22",
            "LA18_CC_P"     : "D17",
            "LA18_CC_N"     : "C17",
            "LA27_P"        : "B20",
            "LA27_N"        : "A20",
            "CLK1_M2C_P"    : "C18",
            "CLK1_M2C_N"    : "C19",
            "LA00_CC_P"     : "K18",
            "LA00_CC_N"     : "K19",
            "LA03_P"        : "N18",
            "LA03_N"        : "N19",
            "LA08_P"        : "M15",
            "LA08_N"        : "M16",
            "LA12_P"        : "L19",
            "LA12_N"        : "L20",
            "LA16_P"        : "G17",
            "LA16_N"        : "G18",
            "LA20_P"        : "F19",
            "LA20_N"        : "F20",
            "LA22_P"        : "E21",
            "LA22_N"        : "D21",
            "LA25_P"        : "F16",
            "LA25_N"        : "E17",
            "LA29_P"        : "C14",
            "LA29_N"        : "C15",
            "LA31_P"        : "E13",
            "LA31_N"        : "E14",
            "LA33_P"        : "F13",
            "LA33_N"        : "F14",
            }
        ),

        # pmods
        Connector("JA", 0,    "AB22 AB21 AB20 AB18 - - Y21 AA21 AA20 AA18 - - "),  # IOSTANDARD=LVCMOS33
        Connector("JB", 0,    "V9   V8   V7   W7   - - W9  Y9   Y8   Y7   - - "),  # IOSTANDARD=LVCMOS33
        Connector("JC", 0,    "Y6   AA6  AA8  AB8  - - R6  T6   AB7  AB6  - - "),  # IOSTANDARD=LVCMOS33
        Connector("JXADC", 0, "J14  H13  G15  J15  - - H14 G13  G16  H15  - - "),  # VCCIO driven by VADJ
    ]


    #
    # Synthesis & configuration
    #


    @property
    def file_templates(self):
        return {
            **super().file_templates,
            "{{name}}-openocd.cfg": r"""
            interface ftdi
            ftdi_device_desc "Digilent USB Device"
            ftdi_vid_pid 0x0403 0x6010
            ftdi_channel 1
            ftdi_layout_init 0x00e8 0x60eb
            reset_config none

            source [find cpld/xilinx-xc7.cfg]
            source [find cpld/jtagspi.cfg]
            adapter_khz 25000

            proc fpga_program {} {
                global _CHIPNAME
                xc7_program $_CHIPNAME.tap
            }
            """,
        }


    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            'add_constraints': "set_property INTERNAL_VREF 0.750 [get_iobanks 35]",
            'script_before_bitstream': "set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]",
        }
        if hasattr(kwargs, 'overrides'):
            overrides.update(kwargs['overrides'])

        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)


    def toolchain_program(self, products, name):
        openocd = os.environ.get("OPENOCD", "openocd")
        with products.extract("{}-openocd.cfg".format(name), "{}.bit".format(name)) \
                as (config_filename, bitstream_filename):
            subprocess.check_call([openocd,
                "-f", config_filename,
                "-c", "transport select jtag; init; fpga_program; pld load 0 {}; exit".format(bitstream_filename)
            ])


