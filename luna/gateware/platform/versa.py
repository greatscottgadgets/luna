#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" ECP5 Versa platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.versa:ECP5Versa_5G_Platform"
"""

from amaranth import *
from amaranth.build import *
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform
from amaranth.lib.cdc import ResetSynchronizer

from amaranth_boards.versa_ecp5_5g import VersaECP55GPlatform as _VersaECP55G
from amaranth_boards.resources import *

from ..interface.pipe       import AsyncPIPEInterface
from ..interface.serdes_phy import ECP5SerDesPIPE

from .core import LUNAPlatform


__all__ = ["ECP5Versa_5G_Platform"]


class VersaDomainGenerator(Elaboratable):
    """ Clock generator for ECP5 Versa boards. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains.
        m.domains.ss     = ClockDomain()
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()


        # Grab our clock and global reset signals.
        clk100 = platform.request(platform.default_clk)
        reset  = platform.request(platform.default_rst)

        # Generate the clocks we need for running our SerDes.
        feedback = Signal()
        usb3_locked = Signal()
        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=clk100,

                # Generated clock outputs.
                o_CLKOP=feedback,
                o_CLKOS= ClockSignal("sync"),
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
                p_CLKOP_CPHASE=4,
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
                p_CLKOP_DIV=5,
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

        # Temporary: USB FS PLL
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

                p_CLKI_DIV = 20,
                p_CLKOP_ENABLE = "ENABLED",
                p_CLKOP_DIV = 16,
                p_CLKOP_CPHASE = 15,
                p_CLKOP_FPHASE = 0,

                p_CLKOS_DIV = 12,
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
                i_CLKI=clk100,

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

        # Control our resets.
        m.d.comb += [
            ClockSignal("ss")      .eq(ClockSignal("sync")),

            # ResetSignal("ss")      .eq(~usb3_locked),
            ResetSignal("sync")    .eq(ResetSignal("ss")),
            ResetSignal("fast")    .eq(ResetSignal("ss")),

            # ResetSignal("usb")     .eq(~usb2_locked),
            ResetSignal("usb_io")  .eq(ResetSignal("usb")),
        ]

        # LOCK is an asynchronous output of the EXHPLL block.
        m.submodules += ResetSynchronizer(~usb2_locked, domain="usb")
        m.submodules += ResetSynchronizer(~usb3_locked, domain="ss")

        return m


class VersaSuperSpeedPHY(AsyncPIPEInterface):
    """ Superspeed PHY configuration for the Versa-5G. """

    REFCLK_FREQUENCY = 312.5e6
    SS_FREQUENCY     = 125.0e6
    FAST_FREQUENCY   = 250.0e6

    SERDES_DUAL    = 0
    SERDES_CHANNEL = 0


    def __init__(self, platform):

        # Grab the I/O that implements our SerDes interface...
        serdes_io_directions = {
            'ch0':    {'tx':"-", 'rx':"-"},
            #'ch1':    {'tx':"-", 'rx':"-"},
            'refclk': '-',
        }
        serdes_io      = platform.request("serdes", self.SERDES_DUAL, dir=serdes_io_directions)
        serdes_channel = getattr(serdes_io, f"ch{self.SERDES_CHANNEL}")

        # Use it to create our soft PHY...
        serdes_phy = ECP5SerDesPIPE(
            tx_pads             = serdes_channel.tx,
            rx_pads             = serdes_channel.rx,
            dual                = self.SERDES_DUAL,
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

        # Enable the Versa's reference clock.
        m.d.comb += platform.request("refclk_enable").o.eq(1)

        return m



class ECP5Versa_5G_Platform(_VersaECP55G, LUNAPlatform):
    name                   = "ECP5 Versa 5G"

    clock_domain_generator = VersaDomainGenerator
    default_usb3_phy       = VersaSuperSpeedPHY
    default_usb_connection = None

    additional_resources = [

        Resource("serdes", 0,
            Subsignal("ch0",
                Subsignal("rx", DiffPairs("Y5", "Y6")),
                Subsignal("tx", DiffPairs("W4", "W5")),
            ),
            #Subsignal("ch1",
            #    Subsignal("rx", DiffPairs("Y7", "Y8")),
            #    Subsignal("tx", DiffPairs("W8", "W9"))
            #),
            #Subsignal("refclk", DiffPairs("Y11", "Y12"))
        ),

        # The SerDes reference clock oscillator must be explicitly enabled.
        Resource("refclk_enable", 0, Pins("C12", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        # Temporary USB connection, for debugging.
        DirectUSBResource(0, d_p="A8", d_n="A12", pullup="B13", attrs=Attrs(IO_TYPE="LVCMOS33"))
    ]

    # Create our semantic aliases.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_resources(self.additional_resources)
