#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Hackaday SuperCon 2019 Badge Platform definitions.

This is an -unsupported- platform! To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.hackaday:Supercon2020Badge"

This board is not routinely tested, and performance is not guaranteed.
"""

import os
import logging
import subprocess

from nmigen import Elaboratable, ClockDomain, Module, ClockSignal, Instance, Signal
from nmigen.build import Resource, Subsignal, Pins, PinsN, Attrs, Clock, Connector

from nmigen.vendor.lattice_ecp5 import LatticeECP5Platform

from .core import LUNAPlatform


class SuperconDomainGenerator(Elaboratable):
    """ Simple clock domain generator for the Hackaday Supercon badge. """

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

        m.submodules.pll = Instance("EHXPLLL",

                # Status.
                #o_LOCK=self._pll_lock,

                # PLL parameters...
                p_PLLRST_ENA="DISABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_OUTDIVIDER_MUXB="DIVB",
                p_OUTDIVIDER_MUXC="DIVC",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKI_DIV = 1,
                p_CLKOP_ENABLE = "ENABLED",
                p_CLKOP_DIV = 12,
                p_CLKOP_CPHASE = 5,
                p_CLKOP_FPHASE = 0,
                p_CLKOS2_ENABLE = "ENABLED",
                p_CLKOS2_DIV = 48,
                p_CLKOS2_CPHASE = 5,
                p_CLKOS2_FPHASE = 0,
                p_FEEDBK_PATH = "CLKOP",
                p_CLKFB_DIV = 6,

                # Clock in.
                i_CLKI=input_clock,

                # Internal feedback.
                i_CLKFB=ClockSignal("sync"),

                # Control signals.
                i_RST=0,
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
                o_CLKOP=ClockSignal("sync"),
                o_CLKOS2=ClockSignal("usb"),

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="8",
                a_FREQUENCY_PIN_CLKOP="48",
                a_FREQUENCY_PIN_CLKOS2="12",
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8",
                a_MFG_ENABLE_FILTEROPAMP="1",
                a_MFG_GMCREF_SEL="2"
        )

        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync"))
        ]

        return m


class Supercon2020Badge(LatticeECP5Platform, LUNAPlatform):
    """ Platform for the Supercon 2020 badge (final, black PCB). """

    name        = "HAD Supercon 2020 Badge"

    device      = "LFE5U-45F"
    package     = "BG381"
    speed       = "8"

    default_clk = "clk8"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = SuperconDomainGenerator

    # We only have a direct connection on our USB lines, so use that for USB comms.
    default_usb_connection = "usb"

    #
    # I/O resources.
    #
    resources   = [
        Resource("clk8", 0, Pins("U18"), Clock(8e6), Attrs(IOStandard="LVCMOS33")),
        Resource("programn", 0, Pins("R1"), Attrs(IOStandard="LVCMOS33")),
        Resource("serial", 0,
            Subsignal("rx", Pins("U2"), Attrs(IOStandard="LVCMOS33"), Attrs(PULLMODE="UP")),
            Subsignal("tx", Pins("U1"), Attrs(IOStandard="LVCMOS33")),
        ),

        # Full LED array.
        Resource("led_anodes", 0, Pins("E3 D3 C3 C4 C2 B1 B20 B19 A18 K20 K19"), Attrs(IOStandard="LVCMOS33")),  # Anodes
        Resource("led_cathodes", 1, Pins("P19 L18 K18"), Attrs(IOStandard="LVCMOS33")), # Cathodes via FET

        # Compatibility aliases.
        Resource("led", 0, Pins("E3")),
        Resource("led", 1, Pins("D3")),
        Resource("led", 2, Pins("C3")),
        Resource("led", 3, Pins("C4")),
        Resource("led", 4, Pins("C2")),
        Resource("led", 5, Pins("B1")),

        Resource("usb", 0,
            Subsignal("d_p", Pins("F3")),
            Subsignal("d_n", Pins("G3")),
            Subsignal("pullup", Pins("E4", dir="o")),
            Subsignal("vbus_valid", Pins("F4", dir="i")),
            Attrs(IOStandard="LVCMOS33")
        ),
        Resource("keypad", 0,
            Subsignal("left", Pins("G2"), Attrs(PULLMODE="UP")),
            Subsignal("right", Pins("F2"), Attrs(PULLMODE="UP")),
            Subsignal("up", Pins("F1"), Attrs(PULLMODE="UP")),
            Subsignal("down", Pins("C1"), Attrs(PULLMODE="UP")),
            Subsignal("start", Pins("E1"), Attrs(PULLMODE="UP")),
            Subsignal("select", Pins("D2"), Attrs(PULLMODE="UP")),
            Subsignal("a", Pins("D1"), Attrs(PULLMODE="UP")),
            Subsignal("b", Pins("E2"), Attrs(PULLMODE="UP")),
        ),
        Resource("hdmi_out", 0,
            Subsignal("clk_p", PinsN("P20"), Attrs(IOStandard="TMDS_33")),
            Subsignal("clk_n", PinsN("R20"), Attrs(IOStandard="TMDS_33")),
            Subsignal("data0_p", Pins("N19"), Attrs(IOStandard="TMDS_33")),
            Subsignal("data0_n", Pins("N20"), Attrs(IOStandard="TMDS_33")),
            Subsignal("data1_p", Pins("L20"), Attrs(IOStandard="TMDS_33")),
            Subsignal("data1_n", Pins("M20"), Attrs(IOStandard="TMDS_33")),
            Subsignal("data2_p", Pins("L16"), Attrs(IOStandard="TMDS_33")),
            Subsignal("data2_n", Pins("L17"), Attrs(IOStandard="TMDS_33")),
            Subsignal("hpd_notif", PinsN("R18"), Attrs(IOStandard="LVCMOS33")),  # Also called HDMI_HEAC_n
            Subsignal("hdmi_heac_p", PinsN("T19"), Attrs(IOStandard="LVCMOS33")),
            Attrs(DRIVE=4),
        ),
        Resource("lcd", 0,
            Subsignal("db", Pins("J3 H1 K4 J1 K3 K2 L4 K1 L3 L2 M4 L1 M3 M1 N4 N2 N3 N1"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("rd", Pins("P2"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("wr", Pins("P4"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("rs", Pins("P1"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("cs", Pins("P3"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("id", Pins("J4"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("rst", Pins("H2"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("fmark", Pins("G1"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("blen", Pins("P5"), Attrs(IOStandard="LVCMOS33")),
        ),
        Resource("spiflash", 0, # clock needs to be accessed through USRMCLK
            Subsignal("cs_n", Pins("R2"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("mosi", Pins("W2"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("miso", Pins("V2"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("wp",   Pins("Y2"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("hold", Pins("W1"), Attrs(IOStandard="LVCMOS33")),
        ),
        Resource("spiflash4x", 0, # clock needs to be accessed through USRMCLK
            Subsignal("cs_n", Pins("R2"), Attrs(IOStandard="LVCMOS33")),
            Subsignal("dq",   Pins("W2 V2 Y2 W1"), Attrs(IOStandard="LVCMOS33")),
        ),
        Resource("spiram4x", 0,
            Subsignal("cs_n", Pins("D20"), Attrs(IOStandard="LVCMOS33"), Attrs(SLEWRATE="SLOW")),
            Subsignal("clk",  Pins("E20"), Attrs(IOStandard="LVCMOS33"), Attrs(SLEWRATE="SLOW")),
            Subsignal("dq",   Pins("E19 D19 C20 F19"), Attrs(IOStandard="LVCMOS33"), Attrs(PULLMODE="UP"), Attrs(SLEWRATE="SLOW")),
        ),
        Resource("spiram4x", 1,
            Subsignal("cs_n", Pins("F20"), Attrs(IOStandard="LVCMOS33"), Attrs(SLEWRATE="SLOW")),
            Subsignal("clk",  Pins("J19"), Attrs(IOStandard="LVCMOS33"), Attrs(SLEWRATE="SLOW")),
            Subsignal("dq",   Pins("J20 G19 G20 H20"), Attrs(IOStandard="LVCMOS33"), Attrs(PULLMODE="UP"), Attrs(SLEWRATE="SLOW")),
        ),
        Resource("sao", 0,
            Subsignal("sda", Pins("B3")),
            Subsignal("scl", Pins("B2")),
            Subsignal("gpio", Pins("A2 A3 B4")),
            Subsignal("drm", Pins("A4")),
        ),
        Resource("sao", 1,
            Subsignal("sda", Pins("A16")),
            Subsignal("scl", Pins("B17")),
            Subsignal("gpio", Pins("B18 A17 B16")),
            Subsignal("drm", Pins("C17")),
        ),
        Resource("testpts", 0,
            Subsignal("a1", Pins("A15")),
            Subsignal("a2", Pins("C16")),
            Subsignal("a3", Pins("A14")),
            Subsignal("a4", Pins("D16")),
            Subsignal("b1", Pins("B15")),
            Subsignal("b2", Pins("C15")),
            Subsignal("b3", Pins("A13")),
            Subsignal("b4", Pins("B13")),
        ),
        Resource("sdram_clock", 0, Pins("D11"), Attrs(IOStandard="LVCMOS33")),
        Resource("sdram", 0,
            Subsignal("a", Pins("A8 D9 C9 B9 C14 E17 A12 B12 H17 G18 B8 A11 B11")),
            Subsignal("dq", Pins("C5 B5 A5 C6 B10 C10 D10 A9")),
            Subsignal("we_n", Pins("B6")),
            Subsignal("ras_n", Pins("D6")),
            Subsignal("cas_n", Pins("A6")),
            Subsignal("cs_n", Pins("C7")),
            Subsignal("cke", Pins("C11")),
            Subsignal("ba", Pins("A7 C8")),
            Subsignal("dm", Pins("A10")),
            Attrs(IOStandard="LVCMOS33"), Attrs(SLEWRATE="FAST")
        ),

        # Compatibility.
        Resource("user_io", 0, Pins("A15")),
        Resource("user_io", 1, Pins("C16")),
        Resource("user_io", 2, Pins("A14")),
        Resource("user_io", 3, Pins("D16")),
    ]

    connectors = [
        Connector("pmod", 0, "A15 C16 A14 D16 B15 C15 A13 B13"),
        Connector("genio", 0, "C5 B5 A5 C6 B6 A6 D6 C7 A7 C8 B8 A8 D9 C9 B9 A9 D10 C10 B10 A10 D11 C11 B11 A11 G18 H17 B12 A12 E17 C14"),
    ]

    def __init__(self, *args, **kwargs):
        logging.warning("This platform is not officially supported, and thus not tested.")
        logging.warning("Your results may vary.")
        super().__init__(*args, **kwargs)


    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            'ecppack_opts': '--compress --freq 38.8'
        }
        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)


    def toolchain_program(self, products, name):
        """ Program the flash of an Supercon board. """

        # Use the DFU bootloader to program the ECP5 bitstream.
        dfu_util = os.environ.get("DFU_UTIL", "dfu-util")
        with products.extract("{}.bit".format(name)) as bitstream_filename:
            subprocess.check_call([dfu_util, "-d", "1d50:614b", "-a", "0", "-D", bitstream_filename])


    def toolchain_flash(self, products, name="top"):
        """ Program the flash of an Supercon cartridge. """

        # Use the DFU bootloader to program the ECP5 bitstream.
        dfu_util = os.environ.get("DFU_UTIL", "dfu-util")
        with products.extract("{}.bit".format(name)) as bitstream_filename:
            subprocess.check_call([dfu_util, "-d", "1d50:614b", "-a", "2", "-D", bitstream_filename])
