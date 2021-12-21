#
# This file is part of LUNA.
#
# Copyright (c) 2019 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Hackaday SuperCon 2019 Badge Platform definitions.

This is an -unsupported- platform! To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.hackaday:Supercon19BadgePlatform"

This board is not routinely tested, and performance is not guaranteed.
"""

import os
import logging
import subprocess

from amaranth import *
from amaranth.build import *
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform

from amaranth_boards.resources import *


from .core import LUNAPlatform


class SuperconDomainGenerator(Elaboratable):
    """ Simple clock domain generator for the Hackaday Supercon badge. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()
        locked = Signal()

        # Grab our default input clock.
        input_clock = platform.request(platform.default_clk, dir="i")

        # Create our domains; but don't do anything else for them, for now.
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        m.submodules.pll = Instance("EHXPLLL",

                # Status.
                o_LOCK=locked,

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
            ClockSignal("fast")    .eq(ClockSignal("sync")),

            ResetSignal("sync")    .eq(~locked),
            ResetSignal("usb")     .eq(~locked),
            ResetSignal("usb_io")  .eq(~locked),
            ResetSignal("fast")    .eq(~locked),
        ]

        return m

#
# This is sitting here in LUNA until it's accepted into amaranth-boards.
#
class _Supercon19BadgePlatform(LatticeECP5Platform):
    device      = "LFE5U-45F"
    package     = "BG381"
    speed       = "8"
    default_clk = "clk8"

    # The badge's LEDs are wired in a non-straightforward way. Here, the
    # LEDResources represent each of the common anodes of a collection of RGB LEDs.
    # A single one of their cathodes defaults to connected via a FET; the other
    # cathodes are normally-off. Accordingly, they act as normal single-color LEDs
    # unless the cathode signals are explicitly driven.
    #
    # The LEDs on the badge were meant to be a puzzle; so each cathode signal
    # corresponds to a different color on each LED. This means there's no
    # straightforward way of creating pin definitions; you'll need to use the
    # following mapping to find the cathode pin number below.
    led_cathode_mappings = [
        {'r': 0, 'g': 1, 'b': 2}, # LED1: by default, red
        {'r': 2, 'g': 1, 'b': 0}, # LED2: by default, blue
        {'r': 0, 'g': 1, 'b': 2}, # LED3: by default, red
        {'r': 2, 'g': 1, 'b': 0}, # LED4: by default, blue
        {'r': 0, 'g': 1, 'b': 2}, # LED5: by default, red
        {'r': 2, 'g': 1, 'b': 0}, # LED6: by default, blue
        {'r': 2, 'g': 0, 'b': 1}, # LED7: by default, green
        {'r': 0, 'g': 1, 'b': 2}, # LED8: by default, red
        {'r': 0, 'g': 1, 'b': 2}, # LED9: by default, red
        # Note: [LED10 is disconnected by default; bridge R60 to make things work]
        {'r': 2, 'g': 1, 'b': 0}, # LED10: by default, blue
        {'r': 1, 'g': 0, 'b': 2}, # LED11: by default, green
    ]

    resources   = [
        Resource("clk8", 0, Pins("U18"), Clock(8e6), Attrs(IO_TYPE="LVCMOS33")),

        # Used to trigger FPGA reconfiguration.
        Resource("program", 0, PinsN("R1"), Attrs(IO_TYPE="LVCMOS33")),

        # See note above for LED anode/cathode information.
        # Short version is: these work as normal LEDs until you touch their cathodes.
        *LEDResources(pins="E3 D3 C3 C4 C2 B1 B20 B19 A18 K20 K19",
            attrs=Attrs(IO_TYPE="LVCMOS33")),
        Resource("led_cathodes", 0, Pins("P19 L18 K18"), Attrs(IO_TYPE="LVCMOS33")),

        UARTResource(0, rx="U2", tx="U1", attrs=Attrs(IO_TYPE="LVCMOS33")),

        DirectUSBResource(0, d_p="F3", d_n="G3", pullup="E4", vbus_valid="F4",
            attrs=Attrs(IO_TYPE="LVCMOS33")),

        # Buttons, with semantic aliases.
        *ButtonResources(pins="G2 F2 F1 C1 E1 D2 D1 E2",
            attrs=Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")
        ),
        Resource("keypad", 0,
            Subsignal("left",  Pins("G2", dir="i")),
            Subsignal("right", Pins("F2", dir="i")),
            Subsignal("up",    Pins("F1", dir="i")),
            Subsignal("down",  Pins("C1", dir="i")),
            Subsignal("start", Pins("E1", dir="i")),
            Subsignal("select",Pins("D2", dir="i")),
            Subsignal("a",     Pins("D1", dir="i")),
            Subsignal("b",     Pins("E2", dir="i")),
            Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")
        ),

        # Direct HDMI on the bottom of the board.
        Resource("hdmi", 0,
            Subsignal("clk", DiffPairsN("P20", "R20"), Attrs(IO_TYPE="TMDS_33")),
            Subsignal("d", DiffPairs("N19 L20 L16", "N20 M20 L17"), Attrs(IO_TYPE="TMDS_33")),
            Subsignal("hpd", PinsN("R18"), Attrs(IO_TYPE="LVCMOS33")),# Also called HDMI_HEAC_n
            Subsignal("hdmi_heac_p", PinsN("T19"), Attrs(IO_TYPE="LVCMOS33")),
            Attrs(DRIVE="4"),
        ),

        Resource("lcd", 0,
            Subsignal("db",
                Pins("J3 H1 K4 J1 K3 K2 L4 K1 L3 L2 M4 L1 M3 M1 N4 N2 N3 N1"),
            ),
            Subsignal("rd",    Pins("P2")),
            Subsignal("wr",    Pins("P4")),
            Subsignal("rs",    Pins("P1")),
            Subsignal("cs",    Pins("P3")),
            Subsignal("id",    Pins("J4")),
            Subsignal("rst",   Pins("H2")),
            Subsignal("fmark", Pins("G1")),
            Subsignal("blen",  Pins("P5")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        Resource("spi_flash", 0, # clock needs to be accessed through USRMCLK
            Subsignal("cs",   PinsN("R2")),
            Subsignal("copi", Pins("W2")),
            Subsignal("cipo", Pins("V2")),
            Subsignal("wp",   Pins("Y2")),
            Subsignal("hold", Pins("W1")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("spi_flash_4x", 0, # clock needs to be accessed through USRMCLK
            Subsignal("cs",   PinsN("R2")),
            Subsignal("dq",   Pins("W2 V2 Y2 W1")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # SPI-connected PSRAM.
        Resource("spi_ram_4x", 0,
            Subsignal("cs",  PinsN("D20")),
            Subsignal("clk", Pins("E20")),
            Subsignal("dq",  Pins("E19 D19 C20 F19"), Attrs(PULLMODE="UP")),
            Attrs(IO_TYPE="LVCMOS33", SLEWRATE="SLOW")
        ),
        Resource("spi_ram_4x", 1,
            Subsignal("cs",   PinsN("F20")),
            Subsignal("clk",  Pins("J19")),
            Subsignal("dq",   Pins("J20 G19 G20 H20"), Attrs(PULLMODE="UP")),
            Attrs(IO_TYPE="LVCMOS33", SLEWRATE="SLOW")
        ),

        SDRAMResource(0, clk="D11", cke="C11", cs="C7", we="B6", ras="D6", cas="A6",
            ba="A7 C8", a="A8 D9 C9 B9 C14 E17 A12 B12 H17 G18 B8 A11 B11",
            dq="C5 B5 A5 C6 B10 C10 D10 A9", dqm="A10",
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")
        )
    ]

    connectors = [
        Connector("pmod", 0, "A15 C16 A14 D16 B15 C15 A13 B13"),
        Connector("cartridge", 0,
            "- - - - - - - - C5 B5 A5 C6 B6 A6 D6 C7 A7 C8 B8 A8 D9 C9 B9 A9" # continued:
            " D10 C10 B10 A10 D11 C11 B11 A11 G18 H17 B12 A12 E17 C14"
        ),

        # SAO connectors names are compliant with the, erm, SAO 1.69 X-TREME standard.
        # See: https://hackaday.com/2019/03/20/introducing-the-shitty-add-on-v1-69bis-standard/
        Connector("sao", 0, {
            "sda":   "B3", "scl":   "B2", "gpio0": "A2",
            "gpio1": "A3", "gpio2": "B4", "gpio3": "A4"
        }),
        Connector("sao", 1, {
            "sda":   "A16", "scl":   "B17", "gpio0": "B18",
            "gpio1": "A17", "gpio2": "B16", "gpio3": "C17"
        })
    ]

    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = dict(ecppack_opts="--compress --freq 38.8")
        overrides.update(kwargs)
        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)

    def toolchain_program(self, products, name):
        dfu_util = os.environ.get("DFU_UTIL", "dfu-util")
        with products.extract("{}.bit".format(name)) as bitstream_filename:
            subprocess.check_call([dfu_util, "-d", "1d50:614b", "-a", "0", "-D", bitstream_filename])



class Supercon19BadgePlatform(_Supercon19BadgePlatform, LUNAPlatform):
    name                   = "HAD Supercon 2019 Badge"
    clock_domain_generator = SuperconDomainGenerator
    default_usb_connection = "usb"
