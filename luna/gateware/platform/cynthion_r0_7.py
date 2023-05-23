#
# This file is part of LUNA.
#
# Copyright (c) 2020-2023 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os

from amaranth.build import *
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform
from amaranth_boards.resources import *

from .core import LUNAApolloPlatform
from ..architecture.car import LunaECP5DomainGenerator

__all__ = ["CynthionPlatformRev0D7"]

class CynthionPlatformRev0D7(LUNAApolloPlatform, LatticeECP5Platform):
    """ Board description for Cynthion r0.7 """

    name        = "Cynthion r0.7"

    device      = "LFE5U-25F"
    package     = "BG256"
    speed       = os.getenv("ECP5_SPEED_GRADE", "8")

    default_clk = "clk_60MHz"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = LunaECP5DomainGenerator

    # By default, assume we'll be connecting via our target PHY.
    default_usb_connection = "target_phy"

    #
    # Default clock frequencies for each of our clock domains.
    #
    # Different revisions have different FPGA speed grades, and thus the
    # default frequencies will vary.
    #
    DEFAULT_CLOCK_FREQUENCIES_MHZ = {
        "fast": 240,
        "sync": 120,
        "usb":  60
    }

    #
    # Preferred DRAM bus I/O (de)-skewing constants.
    #
    ram_timings = dict(
        # Set max skew to meet IO setup times
        # TODO: remove this & use the PLL to produce a 90degree clock signal instead.
        clock_skew = 127
    )

    # Provides any platform-specific ULPI registers necessary.
    # This is the spot to put any platform-specific vendor registers that need
    # to be written.
    ulpi_extra_registers = {
        0x39: 0b000110 # USB3343: swap D+ and D- to match the hardware design
    }

    #
    # I/O resources.
    #
    resources   = [

        # Primary, discrete 60MHz oscillator.
        Resource("clk_60MHz", 0, Pins("A8", dir="i"),
            Clock(60e6), Attrs(IO_TYPE="LVCMOS33")),

        # Connection to our SPI flash; can be used to work with the flash
        # from e.g. a bootloader.
        Resource("spi_flash", 0,

            # SCK is on pin 9; but doesn't have a traditional I/O buffer.
            # Instead, we'll need to drive a clock into a USRMCLK instance.
            # See interfaces/flash.py for more information.
            Subsignal("sdi",  Pins("T8",  dir="o")),
            Subsignal("sdo",  Pins("T7",  dir="i")),
            Subsignal("cs",   PinsN("N8", dir="o")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # Note: UART pins R14 and T14 are connected to JTAG pins R11 (TDI)
        # and T11 (TMS) respectively, so the microcontroller can use either
        # function but not both simultaneously.

        # UART connected to the debug controller; can be routed to a host via CDC-ACM.
        Resource("uart", 0,
            Subsignal("rx",  Pins("R14",  dir="i")),
            Subsignal("tx",  Pins("T14",  dir="oe"), Attrs(PULLMODE="UP")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # interrupt output to send signal to microcontroller
        Resource("int", 0, Pins("R8", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        # USER button
        Resource("button_user", 0, PinsN("M14", dir="i"), Attrs(IO_TYPE="LVCMOS33", PULLMODE="NONE")),

        # output signal connected to PROGRAMN to trigger FPGA reconfiguration
        Resource("self_program", 0, PinsN("T13", dir="o"), Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")),

        # FPGA LEDs
        *LEDResources(pins="E13 C13 B14 A15 D12 C11", attrs=Attrs(IO_TYPE="LVCMOS33"), invert=True),

        # USB PHYs
        ULPIResource("control_phy", 0,
            data="N16 N14 P16 P15 R16 R15 T15 P14", clk="L14", clk_dir='o',
            dir="M16", nxt="M15", stp="L15", rst="L16", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        ULPIResource("aux_phy", 0,
            data="J16 K15 K16 J13 J14 H13 H14 K14", clk="F16", clk_dir='o',
            dir="H15", nxt="J15", stp="G16", rst="G15", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        ULPIResource("target_phy", 0,
            data="R2 R1 P2 P1 N3 N1 M2 M1", clk="T4", clk_dir='o',
            dir="R3", nxt="T2", stp="T3", rst="R4", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),

        # direct connection to TARGET USB D+/D-
        Resource("target_usb_diff", 0, DiffPairs("N4", "P3", dir="i"), Attrs(IO_TYPE="LVDS", PULLMODE="NONE")),

        # USB Type-C controllers and pins
        Resource("target_type_c", 0,
            Subsignal("scl",   Pins( "A4", dir="o" ), Attrs(PULLMODE="NONE")),
            Subsignal("sda",   Pins( "C4", dir="io"), Attrs(PULLMODE="NONE")),
            Subsignal("int",   PinsN("A3", dir="i" ), Attrs(PULLMODE="UP")),
            Subsignal("fault", PinsN("D4", dir="i" ), Attrs(PULLMODE="UP")),
            Subsignal("sbu1",  Pins( "A2", dir="io")),
            Subsignal("sbu2",  Pins( "E4", dir="io")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("aux_type_c", 0,
            Subsignal("scl",   Pins( "D16", dir="o" ), Attrs(PULLMODE="NONE")),
            Subsignal("sda",   Pins( "E15", dir="io"), Attrs(PULLMODE="NONE")),
            Subsignal("int",   PinsN("H12", dir="i" ), Attrs(PULLMODE="UP")),
            Subsignal("fault", PinsN("G14", dir="i" ), Attrs(PULLMODE="UP")),
            Subsignal("sbu1",  Pins( "E16", dir="io")),
            Subsignal("sbu2",  Pins( "F15", dir="io")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # power input shutoff
        Resource("control_vbus_in_en", 0, PinsN("K13", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("aux_vbus_in_en",     0, PinsN("L13", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        # VBUS passthrough
        #
        # VBUS on each of the Type-C ports can be connected to TARGET A through
        # a bidirectional switch. If any of these switches is enabled, TARGET A
        # is considered an output. An additional switch can be enabled to pass
        # VBUS through to another port in addition to TARGET A.
        #
        # The TARGET C switch is enabled by default, even when Cynthion is
        # powered off, enabling VBUS passthrough from TARGET C to TARGET A.

        Resource("target_c_vbus_en",   0, PinsN("K5", dir="o"), Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")),
        Resource("control_vbus_en",    0, Pins("L1", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("aux_vbus_en",        0, Pins("L2", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("target_a_discharge", 0, Pins("K4", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        # voltage and current monitor
        Resource("power_monitor", 0,
            Subsignal("scl",   Pins( "C6", dir="o" ), Attrs(PULLMODE="NONE")),
            Subsignal("sda",   Pins( "D6", dir="io"), Attrs(PULLMODE="NONE")),
            Subsignal("pwrdn", PinsN("C7", dir="o" )),
            Subsignal("slow",  Pins( "D5", dir="io")),
            Subsignal("gpio",  Pins( "D7", dir="io")),
            Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")
        ),

        # HyperRAM
        Resource("ram", 0,
            Subsignal("clk",   DiffPairs("C3", "D3", dir="o"), Attrs(IO_TYPE="LVCMOS33D")),
            Subsignal("dq",    Pins("F2 B1 C2 E1 E3 E2 F3 G4", dir="io")),
            Subsignal("rwds",  Pins( "D1", dir="io")),
            Subsignal("cs",    PinsN("B2", dir="o")),
            Subsignal("reset", PinsN("C1", dir="o")),
            Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")
        ),

        # User I/O connections.
        Resource("user_pmod", 0, Pins("C9 B9 D11 C12 C8 D8 D9 C10", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_pmod", 1, Pins("B4 B5 B6 B7 C5 A5 A6 A7", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_mezzanine", 0,
                Pins("B8 A9 B10 A10 B11 D14 C14 F14 E14 G13 G12 C16 C15 B16 B15 A14 B13 A13 D13 A12 B12 A11", dir="io"),
                Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
    ]

    connectors = [
        Connector("pmod", 0, "C9 C8 D11 C12 - - B8 D8 D9 C10 - -"), # PMOD A
        Connector("pmod", 1, "B4 B5 B6 B7 - - C5 A5 A6 A7 - -"), # PMOD B
        Connector("mezzanine", 0,
            "- - B8 A9 B10 A10 B11 D14 C14 F14 E14 G13 G12 - - - - C16 C15 B16 B15 A14 B13 A13 D13 A12 B12 A11 - -"),
    ]

    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            'ecppack_opts': '--compress --freq 38.8'
        }

        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)
