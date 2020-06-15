#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" OrangeCrab platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.orangecrab:OrangeCrabR0D2"
"""

import os
import subprocess

from nmigen import Elaboratable, ClockDomain, Module, ClockSignal, Instance, Signal
from nmigen.build import Resource, Subsignal, Pins, Attrs, Clock, Connector

from nmigen.vendor.lattice_ecp5 import LatticeECP5Platform

from .core import LUNAPlatform


class OrangeCrabDomainGenerator(Elaboratable):
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

        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=input_clock,

                # Generated clock outputs.
                o_CLKOP=ClockSignal("sync"),
                o_CLKOS=ClockSignal("usb"),

                # Status.
                #o_LOCK=self._pll_lock,

                # PLL parameters...
                p_PLLRST_ENA="DISABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_CLKOS3_FPHASE=0,
                p_CLKOS3_CPHASE=0,
                p_CLKOS2_FPHASE=0,
                p_CLKOS2_CPHASE=7,
                p_CLKOS_FPHASE=0,
                p_CLKOS_CPHASE=5,
                p_CLKOP_FPHASE=0,
                p_CLKOP_CPHASE=5,
                p_PLL_LOCK_MODE=0,
                p_CLKOS_TRIM_DELAY="0",
                p_CLKOS_TRIM_POL="FALLING",
                p_CLKOP_TRIM_DELAY="0",
                p_CLKOP_TRIM_POL="FALLING",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKOS3_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXC="DIVC",
                p_CLKOS2_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXB="DIVB",
                p_CLKOS_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOS3_DIV=1,
                p_CLKOS2_DIV=8,
                p_CLKOS_DIV=48,
                p_CLKOP_DIV=12,
                p_CLKFB_DIV=1,
                p_CLKI_DIV=1,
                p_FEEDBK_PATH="CLKOP",

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
                i_ENCLKOS=0,
                i_ENCLKOS2=0,
                i_ENCLKOS3=0,

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="48.000000",
                a_FREQUENCY_PIN_CLKOS="48.000000",
                a_FREQUENCY_PIN_CLKOP="12.000000",
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8"
        )

        # We'll use our 48MHz clock for everything _except_ the usb_io domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync"))
        ]

        return m


class OrangeCrabPlatform(LatticeECP5Platform, LUNAPlatform):
    """ Base class for OrangeCrab platforms. """

    device      = "LFE5U-25F"
    package     = "MG285"
    speed       = "8"

    default_clk = "clk_48MHz"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = OrangeCrabDomainGenerator

    # We only have a direct connection on our USB lines, so use that for USB comms.
    default_usb_connection = "usb"

    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            'ecppack_opts': '--compress --freq 38.8'
        }

        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)


    def toolchain_program(self, products, name):
        """ Program the flash of an ECP5 OrangeCrab board. """

        # Use the DFU bootloader to program the ECP5 bitstream.
        dfu_util = os.environ.get("DFU_UTIL", "dfu-util")
        with products.extract("{}.bit".format(name)) as bitstream_filename:
            subprocess.check_call([dfu_util, "-d", "1209:5bf0", "-D", bitstream_filename])


class OrangeCrabR0D1(OrangeCrabPlatform, LUNAPlatform):
    """ Board description for OrangeCrab r0.1. """

    name        = "OrangeCrab r0.1"

    #
    # I/O resources.
    #
    resources   = [
        Resource("clk_48MHz", 0, Pins("A9"),  Attrs(IO_TYPE="LVCMOS33"), Clock(48e6)),

        Resource("rgb_led", 0,
            Subsignal("r", Pins("V17"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("g", Pins("T17"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("b", Pins("J3"),  Attrs(IO_TYPE="LVCMOS33")),
        ),

        Resource("ddram", 0,
            Subsignal("a", Pins("A4 D2 C3 C7 D3 D4 D1 B2 C1 A2 A7 C2 C4"),
                Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("ba",    Pins("B6 B7 A6"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("ras_n", Pins("C12"),  Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("cas_n", Pins("D13"),  Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("we_n",  Pins("B12"),  Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("cs_n",  Pins("A12"),  Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("dm", Pins("D16 G16"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("dq", Pins("C17 D15 B17 C16 A15 B13 A17 A13 F17 F16 G15 F15 J16 C18 H16 F18"),
                Attrs(IO_TYPE="SSTL135_I", TERMINATION="75")),
            Subsignal("dqs_p", Pins("B15 G18"), Attrs(IO_TYPE="SSTL135D_I", TERMINATION="OFF", DIFFRESISTOR="100")),
            Subsignal("clk_p", Pins("J18"), Attrs(IO_TYPE="SSTL135D_I")),
            Subsignal("cke",   Pins("D6"),  Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("odt",   Pins("C13"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("reset_n", Pins("B1"), Attrs(IO_TYPE="SSTL135_I")),
            Attrs(SLEWRATE="FAST")
        ),

        Resource("spiflash4x", 0,
            Subsignal("cs_n", Pins("U17")),
            Subsignal("clk",  Pins("U16")),
            Subsignal("dq",   Pins("U18 T18 R18 N18")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        Resource("spi-internal", 0,
            Subsignal("cs_n",   Pins("B11"), Attrs(PULLMODE="UP")),
            Subsignal("clk",    Pins("C11")),
            Subsignal("miso",   Pins("A11"), Attrs(PULLMODE="UP")),
            Subsignal("mosi",   Pins("A10"), Attrs(PULLMODE="UP")),
            Attrs(IO_TYPE="LVCMOS33", SLEWRATE="SLOW")
        ),

        Resource("spisdcard", 0,
            Subsignal("clk",  Pins("K1")),
            Subsignal("mosi", Pins("K2"), Attrs(PULLMODE="UP")),
            Subsignal("cs_n", Pins("M1"), Attrs(PULLMODE="UP")),
            Subsignal("miso", Pins("J1"), Attrs(PULLMODE="UP")),
            Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST"),
        ),
    ]

    connectors = [ Connector("GPIO", 0, "N17 M18 C10 C9 - B10 B9 - - C8 B8 A8 H2 J2 N15 R17 N16 - - - - - - - -") ]



class OrangeCrabR0D2(OrangeCrabPlatform, LUNAPlatform):
    """ Board description for OrangeCrab r0.2. """

    name        = "OrangeCrab r0.2"

    #
    # I/O resources.
    #
    resources   = [

        # System clock.
        Resource("clk_48MHz", 0, Pins("A9"), Attrs(IO_TYPE="LVCMOS33"), Clock(48e6)),

        # Self-reset.
        Resource("rst_n", 0, Pins("V17"), Attrs(IO_TYPE="LVCMOS33")),

        # Buttons.
        Resource("user_button", 0, Pins("J17"), Attrs(IO_TYPE="SSTL135_I")),

        # LEDs.
        Resource("rgb_led", 0,
            Subsignal("r", Pins("K4", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("g", Pins("M3", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("b", Pins("J3", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        ),

        # Create aliases for our LEDs with standard naming.
        Resource("led", 0, Pins("K4", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 1, Pins("M3", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 2, Pins("J3", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        # RAM.
        Resource("ddram", 0,
            Subsignal("a", Pins(
                "C4 D2 D3 A3 A4 D4 C3 B2"
                "B1 D1 A7 C2 B6 C1 A2 C7"),
                Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("ba",    Pins("D6 B7 A6"), Attrs(IO_TYPE="SSTL135_I"),),
            Subsignal("ras_n", Pins("C12"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("cas_n", Pins("D13"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("we_n",  Pins("B12"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("cs_n",  Pins("A12"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("dm", Pins("D16 G16"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("dq", Pins(
                "C17 D15 B17 C16 A15 B13 A17 A13"
                "F17 F16 G15 F15 J16 C18 H16 F18"),
                Attrs(IO_TYPE="SSTL135_I"),
                Attrs(TERMINATION="75")),
            Subsignal("dqs_p", Pins("B15 G18"), Attrs(IO_TYPE="SSTL135D_I"),
                Attrs(TERMINATION="OFF"),
                Attrs(DIFFRESISTOR="100")),
            Subsignal("clk_p", Pins("J18"), Attrs(IO_TYPE="SSTL135D_I")),
            Subsignal("cke",   Pins("D18"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("odt",   Pins("C13"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("reset_n", Pins("L18"), Attrs(IO_TYPE="SSTL135_I")),
            Subsignal("vccio", Pins("K16 D17 K15 K17 B18 C6"), Attrs(IO_TYPE="SSTL135_II")),
            Subsignal("gnd",   Pins("L15 L16"), Attrs(IO_TYPE="SSTL135_II")),
            Attrs(SLEWRATE="FAST")
        ),

        # USB Connector.
        Resource("usb", 0,
            Subsignal("d_p",    Pins("N1", dir="io")),
            Subsignal("d_n",    Pins("M2", dir="io")),
            Subsignal("pullup", Pins("N2", dir="o")),
            Attrs(IO_TYPE="LVCMOS33")
        ),


        # Onboard flash.
        Resource("spiflash4x", 0,
            Subsignal("cs_n", Pins("U17"), Attrs(IO_TYPE="LVCMOS33")),
            #Subsignal("clk",  Pins("U16"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("dq",   Pins("U18 T18 R18 N18"), Attrs(IO_TYPE="LVCMOS33")),
        ),
        Resource("spiflash", 0,
            Subsignal("cs_n", Pins("U17"), Attrs(IO_TYPE="LVCMOS33")),
            #Subsignal("clk",  Pins("U16"), Attrs(IO_TYPE="LVCMOS33")), # Note: CLK is bound using USRMCLK block
            Subsignal("miso", Pins("T18"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("mosi", Pins("U18"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("wp",   Pins("R18"), Attrs(IO_TYPE="LVCMOS33")),
            Subsignal("hold", Pins("N18"), Attrs(IO_TYPE="LVCMOS33")),
        ),

        # SD Card.
        Resource("spisdcard", 0,
            Subsignal("clk",  Pins("K1")),
            Subsignal("mosi", Pins("K2"), Attrs(PULLMODE="UP")),
            Subsignal("cs_n", Pins("M1"), Attrs(PULLMODE="UP")),
            Subsignal("miso", Pins("J1"), Attrs(PULLMODE="UP")),
            Attrs(SLEW="FAST"),
            Attrs(IO_TYPE="LVCMOS33"),
        ),

        # User I/O
        Resource("user_io",  0, Pins("N17")),
        Resource("user_io",  1, Pins("M18")),
        Resource("user_io",  2, Pins("C10")),
        Resource("user_io",  3, Pins("C9")),
        # 4
        Resource("user_io",  5, Pins("B10")),
        Resource("user_io",  6, Pins("B9")),
        # 7
        # 8
        Resource("user_io",  9, Pins("C8")),
        Resource("user_io",  10, Pins("B8")),
        Resource("user_io",  11, Pins("A8")),
        Resource("user_io",  12, Pins("H2")),
        Resource("user_io",  13, Pins("J2")),
        Resource("user_io",  14, Pins("N15")),
        Resource("user_io",  15, Pins("R17")),
        Resource("user_io",  16, Pins("N16")),
        # 17
        Resource("user_io",  18, Pins("L4")),
        Resource("user_io",  19, Pins("N3")),
        Resource("user_io",  20, Pins("N4")),
        Resource("user_io",  21, Pins("H4")),
        Resource("user_io",  22, Pins("G4")),
        Resource("user_io",  23, Pins("T17")),

    ]

    connectors = [ Connector("GPIO", 0, "N17 M18 C10 C9 - B10 B9 - - C8 B8 A8 H2 J2 N15 R17 N16 - L4 N3 N4 H4 G4 T17") ]
