#
# This file is part of LUNA.
#
# Copyright (c) 2020-2021 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os

from amaranth.build import *
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform
from amaranth_boards.resources import *

from .core import LUNAApolloPlatform
from ..architecture.car import LunaECP5DomainGenerator

__all__ = ["LUNAPlatformRev0D2"]

#
# Note that r0.2+ have D+/D- swapped to avoid having to cross D+/D- in routing.
#
# This is supported by a PHY feature that allows you to swap pins 13 + 14.
#

class LUNAPlatformRev0D2(LUNAApolloPlatform, LatticeECP5Platform):
    """ Board description for the pre-release r0.2 revision of LUNA. """

    name        = "LUNA r0.2"

    device      = "LFE5U-12F"
    package     = "BG256"
    speed       = os.getenv("LUNA_SPEED_GRADE", "8")

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
        clock_skew = 64
    )

    # Provides any platform-specific ULPI registers necessary.
    # This is the spot to put any platform-specific vendor registers that need
    # to be written.
    ulpi_extra_registers = {
        0x39: 0b000110 # USB3343: swap D+ and D- to match the LUNA boards
    }


    #
    # I/O resources.
    #
    resources   = [

        # Primary, discrete 60MHz oscillator.
        Resource("clk_60MHz", 0, Pins("A7", dir="i"),
            Clock(60e6), Attrs(IO_TYPE="LVCMOS33")),

        # Connection to our SPI flash; can be used to work with the flash
        # from e.g. a bootloader.
        Resource("spi_flash", 0,

            # SCK is on pin 9; but doesn't have a traditional I/O buffer.
            # Instead, we'll need to drive a clock into a USRMCLK instance.
            # See interfaces/flash.py for more information.
            Subsignal("sdi",  Pins("T8",  dir="o")),
            Subsignal("sdo",  Pins("T7",  dir="i")),

            # In r0.2, the chip select line can either be driven by the FPGA
            # or by the Debug Controller. Accordingly, we'll mark the line as
            # bidirectional, and let the user decide.
            Subsignal("cs",   PinsN("N8", dir="io")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # UART connected to the debug controller; can be routed to a host via CDC-ACM.
        UARTResource(0, rx="R14", tx="T14", attrs=Attrs(IO_TYPE="LVCMOS33")),

        # SPI bus connected to the debug controller, for simple register exchanges.
        # Note that the Debug Controller is the controller on this bus.
        Resource("debug_spi", 0,
            Subsignal("sck",  Pins( "R13", dir="i")),
            Subsignal("sdi",  Pins( "P13", dir="i")),
            Subsignal("sdo",  Pins( "P11", dir="o")),
            Subsignal("cs",   PinsN("T13", dir="i")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # FPGA-connected LEDs.
        *LEDResources(pins="L16 L15 M16 M15 N16 P15", attrs=Attrs(IO_TYPE="LVCMOS33"), invert=True),

        # USB PHYs
        ULPIResource("sideband_phy", 0,
            data="R2 R1 P2 P1 N1 M2 M1 L2", clk="R4", clk_dir='o',
            dir="T3", nxt="T2", stp="T4", rst="R3", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        ULPIResource("host_phy", 0,
            data="G2 G1 F2 F1 E1 D1 C1 B1", clk="K2", clk_dir='o',
            dir="J1", nxt="H2", stp="J2", rst="K1", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        ULPIResource("target_phy", 0,
            data="D16 E15 E16 F15 F16 G15 J16 K16", clk="B15", clk_dir='o',
            dir="C15", nxt="C16", stp="B16", rst="G16", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),

        # Target port power switching.
        Resource("power_a_port",       0, Pins("C14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("pass_through_vbus",  0, Pins("D14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("target_vbus_fault",  0, Pins("K15", dir="i"), Attrs(IO_TYPE="LVCMOS33")),

        # HyperRAM (1V8 domain).
        Resource("ram", 0,
            # Note: our clock uses the pseudo-differential I/O present on the top tiles.
            # This requires a recent version of trellis+nextpnr. If your build complains
            # that LVCMOS18D is an invalid I/O type, you'll need to upgrade.
            Subsignal("clk",   DiffPairs("B14", "A15", dir="o"), Attrs(IO_TYPE="LVCMOS18D")),
            Subsignal("dq",    Pins("A11 B10 B12 A12 B11 A10 B9 A9", dir="io")),
            Subsignal("rwds",  Pins( "A13", dir="io")),
            Subsignal("cs",    PinsN("A14", dir="o")),
            Subsignal("reset", PinsN("B13", dir="o")),
            Attrs(IO_TYPE="LVCMOS18", SLEWRATE="FAST")
        ),

        # User I/O connections.
        Resource("user_io", 0, Pins("A5", dir="io"), Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        Resource("user_io", 1, Pins("A4", dir="io"), Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        Resource("user_io", 2, Pins("A3", dir="io"), Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        Resource("user_io", 3, Pins("A2", dir="io"), Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
    ]

    connectors = [
        Connector("user_io", 0, """
            A5  -  A2
            A4  -  A3
        """)
    ]

    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            'ecppack_opts': '--compress --freq 38.8'
        }

        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)

