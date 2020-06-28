#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" LambdaConcept board platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.lambdaconcept:USB2SnifferPlatform"
"""

import os
import subprocess

from nmigen import Elaboratable, ClockDomain, Module
from nmigen.build import Resource, Subsignal, Pins, PinsN, Attrs, Clock
from nmigen.vendor.xilinx_7series import Xilinx7SeriesPlatform

from .core import LUNAPlatform


def ULPIResource(name, data_sites, clk_site, dir_site, nxt_site, stp_site, reset_site, extras=()):
    """ Generates a set of resources for a ULPI-connected USB PHY. """

    return Resource(name, 0,
        Subsignal("data",  Pins(data_sites,  dir="io")),
        Subsignal("clk",   Pins(clk_site,    dir="i" ), Clock(60e6)),
        Subsignal("dir",   Pins(dir_site,    dir="i" )),
        Subsignal("nxt",   Pins(nxt_site,    dir="i" )),
        Subsignal("stp",   Pins(stp_site,    dir="o" )),
        Subsignal("rst",   Pins(reset_site,  dir="o" )),
        Attrs(IOStandard="LVCMOS33", SLEW="FAST")
    )


class StubClockDomainGenerator(Elaboratable):
    """ Stub clock domain generator; stands in for the typical LUNA one.

    This generator creates domains; but currently does not configuration.
    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains; but don't do anything else for them, for now.
        m.domains.usb = ClockDomain()
        m.domains.fast = ClockDomain()

        return m


class USB2SnifferPlatform(Xilinx7SeriesPlatform, LUNAPlatform):
    """ Board description for OpenVizsla USB analyzer. """

    name        = "LambdaConcept USB2Sniffer"

    device      = "xc7a35t"
    package     = "fgg484"
    speed       = "1"

    default_clk = "clk100"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = StubClockDomainGenerator

    # We only have a single PHY; so use it directly.
    default_usb_connection = "target_phy"

    #
    # I/O resources.
    #
    resources   = [
        Resource("clk100", 0, Pins("J19"), Attrs(IOStandard="LVCMOS33")),

        Resource("led", 0, PinsN("W1"), Attrs(IOStandard="LVCMOS33")),
        Resource("led", 1, PinsN("Y2"), Attrs(IOStandard="LVCMOS33")),

        Resource("rgb_led", 0,
            Subsignal("r", PinsN("W2")),
            Subsignal("g", PinsN("Y1")),
            Subsignal("b", PinsN("W1")),
            Attrs(IOStandard="LVCMOS33"),
        ),

        Resource("rgb_led", 1,
            Subsignal("r", PinsN("AA1")),
            Subsignal("g", PinsN("AB1")),
            Subsignal("b", PinsN("Y2")),
            Attrs(IOStandard="LVCMOS33"),
        ),

        Resource("serial", 0,
            Subsignal("tx", Pins("U21")), # FPGA_GPIO0
            Subsignal("rx", Pins("T21")), # FPGA_GPIO1
            Attrs(IOStandard="LVCMOS33"),
        ),

        Resource("ddram", 0,
            Subsignal("a", Pins(
                "M2 M5 M3 M1 L6 P1 N3 N2"
                "M6 R1 L5 N5 N4 P2 P6"),
                Attrs(IOStandard="SSTL15")),
            Subsignal("ba", Pins("L3 K6 L4"), Attrs(IOStandard="SSTL15")),
            Subsignal("ras_n", Pins("J4"), Attrs(IOStandard="SSTL15")),
            Subsignal("cas_n", Pins("K3"), Attrs(IOStandard="SSTL15")),
            Subsignal("we_n", Pins("L1"), Attrs(IOStandard="SSTL15")),
            Subsignal("dm", Pins("G3 F1"), Attrs(IOStandard="SSTL15")),
            Subsignal("dq", Pins(
                "G2 H4 H5 J1 K1 H3 H2 J5"
                "E3 B2 F3 D2 C2 A1 E2 B1"),
                Attrs(IOStandard="SSTL15", IN_TERM="UNTUNED_SPLIT_50")),
            Subsignal("dqs_p", Pins("K2 E1"), Attrs(IOStandard="DIFF_SSTL15")),
            Subsignal("dqs_n", Pins("J2 D1"), Attrs(IOStandard="DIFF_SSTL15")),
            Subsignal("clk_p", Pins("P5"), Attrs(IOStandard="DIFF_SSTL15")),
            Subsignal("clk_n", Pins("P4"), Attrs(IOStandard="DIFF_SSTL15")),
            Subsignal("cke", Pins("J6"), Attrs(IOStandard="SSTL15")),
            Subsignal("odt", Pins("K4"), Attrs(IOStandard="SSTL15")),
            Subsignal("reset_n", Pins("G1"), Attrs(IOStandard="SSTL15")),
            Attrs(SLEW="FAST"),
        ),

        Resource("flash", 0,
            Subsignal("cs_n", Pins("T19")),
            Subsignal("mosi", Pins("P22")),
            Subsignal("miso", Pins("R22")),
            Subsignal("vpp", Pins("P21")),
            Subsignal("hold", Pins("R21")),
            Attrs(IOStandard="LVCMOS33")
        ),

        Resource("usb_fifo_clock", 0, Pins("D17"), Attrs(IOStandard="LVCMOS33")),
        Resource("usb_fifo", 0,
            Subsignal("rst", Pins("K22")),
            Subsignal("data", Pins("A16 F14 A15 F13 A14 E14 A13 E13 B13 C15 C13 C14 B16 E17 B15 F16"
                                "A20 E18 B20 F18 D19 D21 E19 E21 A21 B21 A19 A18 F20 F19 B18 B17")),
            Subsignal("be", Pins("K16 L16 G20 H20")),
            Subsignal("rxf_n", Pins("M13")),
            Subsignal("txe_n", Pins("L13")),
            Subsignal("rd_n", Pins("K19")),
            Subsignal("wr_n", Pins("M15")),
            Subsignal("oe_n", Pins("L21")),
            Subsignal("siwua", Pins("M16")),
            Attrs(IOStandard="LVCMOS33", SLEW="FAST")
        ),

        Resource("ulpi_sw", 0,
            Subsignal("s",  Pins("Y8", dir="o")),
            Subsignal("oe", PinsN("Y9", dir="o")),
            Attrs(IOStandard="LVCMOS33"),
        ),

        # Host PHY -- connects directly to the host port.
        ULPIResource("target_phy",
            data_sites="AB18 AA18 AA19 AB20 AA20 AB21 AA21 AB22",
            clk_site="W19",
            dir_site="W21", stp_site="Y22", nxt_site="W22", reset_site="V20"),

        # Target PHY -- connects via a switch to the target port.
        ULPIResource("sideband_phy",
            data_sites="AB2 AA3 AB3 Y4 AA4 AB5 AA5 AB6",
            clk_site="V4",
            dir_site="AB7", stp_site="AA6", nxt_site="AB8", reset_site="AA8"),
    ]

    connectors = []

    def toolchain_program(self, products, name):
        xc3sprog = os.environ.get("XC3SPROG", "xc3sprog")
        with products.extract("{}.bit".format(name)) as bitstream_file:
            subprocess.check_call([xc3sprog, "-c", "ft4232h", bitstream_file])
