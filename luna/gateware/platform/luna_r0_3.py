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

__all__ = ["LUNAPlatformRev0D3"]

#
# Note that r0.3 have D+/D- swapped to avoid having to cross D+/D- in routing.
#
# This is supported by a PHY feature that allows you to swap pins 13 + 14.
#

class LUNAPlatformRev0D3(LUNAApolloPlatform, LatticeECP5Platform):
    """ Board description for the pre-release r0.3 revision of LUNA. """

    name        = "LUNA r0.3"

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
        clock_skew = 16
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

        # SPI bus connected to test points for simple register exchanges.
        # The FPGA acts as peripheral, not controller.
        Resource("debug_spi", 0,
            Subsignal("sck",  Pins( "R13", dir="i")),
            Subsignal("sdi",  Pins( "P13", dir="i")),
            Subsignal("sdo",  Pins( "P11", dir="o")),
            Subsignal("cs",   PinsN("T13", dir="i")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # FPGA-connected LEDs numbered 5-0.
        *LEDResources(pins="P14 P16 P15 R16 R15 T15", attrs=Attrs(IO_TYPE="LVCMOS33"), invert=True),

        # USB PHYs
        ULPIResource("sideband_phy", 0,
            data="R1 P3 P1 P2 N1 M2 M1 L2", clk="P4", clk_dir='o',
            dir="T2", nxt="R2", stp="R3", rst="T3", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        ULPIResource("host_phy", 0,
            data="F1 F2 E1 E2 D1 E3 C1 C2", clk="J1", clk_dir='o',
            dir="G1", nxt="G2", stp="H2", rst="J2", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        ULPIResource("target_phy", 0,
            data="E16 F14 F16 F15 G16 G15 H15 J16", clk="C15", clk_dir='o',
            dir="D16", nxt="E15", stp="D14", rst="C16", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),

        # Target port power switching.
        #
        # power_c_port does the reverse of pass_through_vbus, passing power
        # from the Type-A port to the Type-C port. It is intended to be used in
        # conjunction with power_a_port, supplying VBUS to both target ports.

        Resource("power_a_port",         0, Pins("C14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("power_c_port",         0, Pins("F13", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("pass_through_vbus",    0, Pins("B16", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("target_c_to_a_fault",  0, Pins("F12", dir="i"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("target_a_to_c_fault",  0, Pins("E14", dir="i"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("target_5v_to_a_fault", 0, Pins("B15", dir="i"), Attrs(IO_TYPE="LVCMOS33")),

        # HyperRAM (3V3 domain).
        Resource("ram", 0,
            # Note: our clock uses the pseudo-differential I/O present on the top tiles.
            # This requires a recent version of trellis+nextpnr. If your build complains
            # that LVCMOS33D is an invalid I/O type, you'll need to upgrade.
            Subsignal("clk",   DiffPairs("B14", "A15", dir="o"), Attrs(IO_TYPE="LVCMOS33D")),
            Subsignal("dq",    Pins("A11 B10 B12 A12 B11 A10 B9 A9", dir="io")),
            Subsignal("rwds",  Pins( "A13", dir="io")),
            Subsignal("cs",    PinsN("A14", dir="o")),
            Subsignal("reset", PinsN("B13", dir="o")),
            Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")
        ),

        # User I/O connections (SMA connectors).
        Resource("user_io", 0, Pins("C3", dir="io"), Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),
        Resource("user_io", 1, Pins("D3", dir="io"), Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")),

        # Convenience references.
        Resource("user_pmod", 0, Pins("A3 A4 A5 A6 C6 B6 C7 B7", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_pmod", 1, Pins("M5 N5 M4 N3 L4 L5 K4 K5", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
    ]

    connectors = [
        Connector("pmod", 0, "A3 A4 A5 A6 - - C6 B6 C7 B7 - -"), # Pmod A
        Connector("pmod", 1, "M5 N5 M4 N3 - - L4 L5 K4 K5 - -"), # Pmod B
    ]

    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            'ecppack_opts': '--compress --freq 38.8'
        }

        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)
