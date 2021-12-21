#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" LambdaConcept board platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.lambdaconcept:USB2SnifferPlatform"
or

    > export LUNA_PLATFORM="luna.gateware.platform.lambdaconcept:ECPIX5PlatformRev02"
"""

import os
import subprocess

from amaranth import Elaboratable, ClockDomain, Module, ResetSignal
from amaranth.build import Resource, Subsignal, Pins, PinsN, Attrs, Clock, DiffPairs, Connector
from amaranth.vendor.xilinx_7series import Xilinx7SeriesPlatform
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform

from .core import LUNAPlatform
from ..architecture.car import PHYResetController


def ULPIResource(name, data_sites, clk_site, dir_site, nxt_site, stp_site, reset_site, extras=(), attrs=None):
    """ Generates a set of resources for a ULPI-connected USB PHY. """

    attrs = Attrs() if attrs is None else attrs

    return Resource(name, 0,
        Subsignal("data",  Pins(data_sites,  dir="io")),
        Subsignal("clk",   Pins(clk_site,    dir="i" ), Clock(60e6)),
        Subsignal("dir",   Pins(dir_site,    dir="i" )),
        Subsignal("nxt",   Pins(nxt_site,    dir="i" )),
        Subsignal("stp",   Pins(stp_site,    dir="o" )),
        Subsignal("rst",   Pins(reset_site,  dir="o" )),
        attrs
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

        # Handle USB PHY resets.
        m.submodules.usb_reset = controller = PHYResetController()
        m.d.comb += [
            ResetSignal("usb")  .eq(controller.phy_reset)
        ]

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
            dir_site="W21", stp_site="Y22", nxt_site="W22", reset_site="V20",
            attrs=Attrs(IOStandard="LVCMOS33", SLEW="FAST")
            ),

        # Target PHY -- connects via a switch to the target port.
        ULPIResource("sideband_phy",
            data_sites="AB2 AA3 AB3 Y4 AA4 AB5 AA5 AB6",
            clk_site="V4",
            dir_site="AB7", stp_site="AA6", nxt_site="AB8", reset_site="AA8",
            attrs=Attrs(IOStandard="LVCMOS33", SLEW="FAST")
        )
    ]

    connectors = []

    def toolchain_program(self, products, name):
        xc3sprog = os.environ.get("XC3SPROG", "xc3sprog")
        with products.extract("{}.bit".format(name)) as bitstream_file:
            subprocess.check_call([xc3sprog, "-c", "ft4232h", bitstream_file])



class ECPIX5PlatformRev02(LatticeECP5Platform, LUNAPlatform):
    name        = "ECPIX-5 R02"

    device      = "LFE5UM5G-85F"
    package     = "BG554"
    speed       = "8"

    default_clk = "clk100"
    default_rst = "rst"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = StubClockDomainGenerator

    # We only have a single PHY; so use it directly.
    default_usb_connection = "ulpi"

    resources   = [
        Resource("rst", 0, PinsN("AB1", dir="i"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("clk100", 0, Pins("K23", dir="i"), Clock(100e6), Attrs(IO_TYPE="LVCMOS33")),

        # LEDs
        Resource("rgb_led", 0,
            Subsignal("r", Pins("U21")),
            Subsignal("g", Pins("W21")),
            Subsignal("b", Pins("T24")),
            Attrs(IO_TYPE="LVCMOS33"),
        ),
        Resource("rgb_led", 1,
            Subsignal("r", Pins("T23")),
            Subsignal("g", Pins("R21")),
            Subsignal("b", Pins("T22")),
            Attrs(IO_TYPE="LVCMOS33"),
        ),
        Resource("rgb_led", 2,
            Subsignal("r", Pins("P21")),
            Subsignal("g", Pins("R23")),
            Subsignal("b", Pins("P22")),
            Attrs(IO_TYPE="LVCMOS33"),
        ),
        Resource("rgb_led", 3,
            Subsignal("r", Pins("K21")),
            Subsignal("g", Pins("K24")),
            Subsignal("b", Pins("M21")),
            Attrs(IO_TYPE="LVCMOS33"),
        ),

        Resource("uart", 0,
            Subsignal("rx", Pins("R26", dir="i")),
            Subsignal("tx", Pins("R24", dir="o")),
            Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")
        ),

        Resource("eth_rgmii", 0,
            Subsignal("rst",     PinsN("C13", dir="o")),
            Subsignal("mdio",    Pins("A13", dir="io")),
            Subsignal("mdc",     Pins("C11", dir="o")),
            Subsignal("tx_clk",  Pins("A12", dir="o")),
            Subsignal("tx_ctrl", Pins("C9", dir="o")),
            Subsignal("tx_data", Pins("D8 C8 B8 A8", dir="o")),
            Subsignal("rx_clk",  Pins("E11", dir="i")),
            Subsignal("rx_ctrl", Pins("A11", dir="i")),
            Subsignal("rx_data", Pins("B11 A10 B10 A9", dir="i")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("eth_int", 0, PinsN("B13", dir="i"), Attrs(IO_TYPE="LVCMOS33")),

        Resource("ddr3", 0,
            Subsignal("clk",    DiffPairs("H3", "J3", dir="o"), Attrs(IO_TYPE="SSTL135D_I")),
            Subsignal("clk_en", Pins("P1", dir="o")),
            Subsignal("we",     PinsN("R3", dir="o")),
            Subsignal("ras",    PinsN("T3", dir="o")),
            Subsignal("cas",    PinsN("P2", dir="o")),
            Subsignal("a",      Pins("T5 M3 L3 V6 K2 W6 K3 L1 H2 L2 N1 J1 M1 K1", dir="o")),
            Subsignal("ba",     Pins("U6 N3 N4", dir="o")),
            Subsignal("dqs",    DiffPairs("V4 V1", "U5 U2", dir="io"), Attrs(IO_TYPE="SSTL135D_I")),
            Subsignal("dq",     Pins("T4 W4 R4 W5 R6 P6 P5 P4 R1 W3 T2 V3 U3 W1 T1 W2", dir="io")),
            Subsignal("dm",     Pins("J4 H5", dir="o")),
            Subsignal("odt",    Pins("L2", dir="o")),
            Attrs(IO_TYPE="SSTL135_I")
        ),

        Resource("hdmi", 0,
            Subsignal("rst",   PinsN("N6", dir="o")),
            Subsignal("scl",   Pins("C17", dir="io")),
            Subsignal("sda",   Pins("E17", dir="io")),
            Subsignal("pclk",  Pins("C1", dir="o")),
            Subsignal("vsync", Pins("A4", dir="o")),
            Subsignal("hsync", Pins("B4", dir="o")),
            Subsignal("de",    Pins("A3", dir="o")),
            Subsignal("d",
                Subsignal("b", Pins("AD25 AC26 AB24 AB25  B3  C3  D3  B1  C2  D2 D1 E3", dir="o")),
                Subsignal("g", Pins("AA23 AA22 AA24 AA25  E1  F2  F1 D17 D16 E16 J6 H6", dir="o")),
                Subsignal("r", Pins("AD26 AE25 AF25 AE26 E10 D11 D10 C10  D9  E8 H5 J4", dir="o")),
            ),
            Subsignal("mclk",  Pins("E19", dir="o")),
            Subsignal("sck",   Pins("D6", dir="o")),
            Subsignal("ws",    Pins("C6", dir="o")),
            Subsignal("i2s",   Pins("A6 B6 A5 C5", dir="o")),
            Subsignal("int",   PinsN("C4", dir="i")),
            Attrs(IO_TYPE="LVTTL33")
        ),

        Resource("sata", 0,
            Subsignal("tx", DiffPairs("AD16", "AD17", dir="o")),
            Subsignal("rx", DiffPairs("AF15", "AF16", dir="i")),
            Attrs(IO_TYPE="LVDS")
        ),

        ULPIResource("ulpi",
            data_sites="M26 L25 L26 K25 K26 J23 P25 H25",
            clk_site="H24",
            dir_site="F22", stp_site="H23", nxt_site="F23", reset_site="E23",
            attrs=Attrs(IO_TYPE="LVCMOS33")
            ),

        Resource("usbc_cfg", 0,
            Subsignal("scl", Pins("D24", dir="io")),
            Subsignal("sda", Pins("C24", dir="io")),
            Subsignal("dir", Pins("B23", dir="i")),
            Subsignal("id",  Pins("D23", dir="i")),
            Subsignal("int", PinsN("B24", dir="i")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("usbc_mux", 0,
            Subsignal("en",    Pins("C23", dir="oe")),
            Subsignal("amsel", Pins("B26", dir="oe")),
            Subsignal("pol",   Pins("D26", dir="o")),
            #Subsignal("lna",   DiffPairs( "AF9", "AF10", dir="i"), Attrs(IO_TYPE="LVCMOS18D")),
            #Subsignal("lnb",   DiffPairs("AD10", "AD11", dir="o"), Attrs(IO_TYPE="LVCMOS18D")),
            #Subsignal("lnc",   DiffPairs( "AD7",  "AD8", dir="o"), Attrs(IO_TYPE="LVCMOS18D")),
            #Subsignal("lnd",   DiffPairs( "AF6",  "AF7", dir="i"), Attrs(IO_TYPE="LVCMOS18D")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # Compatibility aliases.
        Resource("led", 0, Pins("W21", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 1, Pins("R21", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 2, Pins("R23", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 3, Pins("K24", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        Resource("user_io", 0, Pins("T25")),
        Resource("user_io", 1, Pins("U25")),
        Resource("user_io", 2, Pins("U24")),
        Resource("user_io", 3, Pins("V24")),
    ]

    connectors  = [
        Connector("pmod", 0, "T25 U25 U24 V24 - - T26 U26 V26 W26 - -"),
        Connector("pmod", 1, "U23 V23 U22 V21 - - W25 W24 W23 W22 - -"),
        Connector("pmod", 2, "J24 H22 E21 D18 - - K22 J21 H21 D22 - -"),
        Connector("pmod", 3, " E4  F4  E6  H4 - -  F3  D4  D5  F5 - -"),
        Connector("pmod", 4, "E26 D25 F26 F25 - - A25 A24 C26 C25 - -"),
        Connector("pmod", 5, "D19 C21 B21 C22 - - D21 A21 A22 A23 - -"),
        Connector("pmod", 6, "C16 B17 C18 B19 - - A17 A18 A19 C19 - -"),
        Connector("pmod", 7, "D14 B14 E14 B16 - - C14 A14 A15 A16 - -"),
    ]

    @property
    def file_templates(self):
        return {
            **super().file_templates,
            "{{name}}-openocd.cfg": r"""
            interface ftdi
            ftdi_vid_pid 0x0403 0x6010
            ftdi_channel 0
            ftdi_layout_init 0xfff8 0xfffb
            reset_config none
            adapter_khz 25000
            jtag newtap ecp5 tap -irlen 8 -expected-id 0x81113043
            """
        }

    def toolchain_program(self, products, name):
        openocd = os.environ.get("OPENOCD", "openocd")
        with products.extract("{}-openocd.cfg".format(name), "{}.svf".format(name)) \
                as (config_filename, vector_filename):
            subprocess.check_call([openocd,
                "-f", config_filename,
                "-c", "transport select jtag; init; svf -quiet {}; exit".format(vector_filename)
            ])
