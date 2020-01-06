#
# This file is part of LUNA.
#

from nmigen.build import *
from nmigen.vendor.lattice_ecp5 import *

from luna.apollo import ApolloDebugger
from luna.apollo.jtag import JTAGChain
from luna.apollo.ecp5 import ECP5_JTAGProgrammer

__all__ = ["LUNAPlatformR01"]


def ULPIResource(name, data_sites, clk_site, dir_site, nxt_site, stp_site, reset_site):
    """ Generates a set of resources for a ULPI-connected USB PHY. """

    return Resource(name, 0,
        Subsignal("data",  Pins(data_sites, dir="io")),
        Subsignal("clk",   Pins(clk_site,   dir="o" )),
        Subsignal("dir",   Pins(dir_site,   dir="i" )),
        Subsignal("nxt",   Pins(nxt_site,   dir="i" )),
        Subsignal("stp",   Pins(stp_site,   dir="o" )),
        Subsignal("reset", PinsN(clk_site,  dir="o" )),
        Attrs(IO_TYPE="LVCMOS33")
    )


class LUNAPlatformR01(LatticeECP5Platform):
    """ Board description for the pre-release r0.1 revision of LUNA. """

    device      = "LFE5U-12F"
    package     = "BG256"
    speed       = "6"

    default_clk = "clk_60MHz"

    resources   = [

        # Primary, discrete 60MHz oscillator.
        Resource("clk_60MHz", 0, Pins("A8", dir="i"), 
            Clock(60e6), Attrs(IO_TYPE="LVCMOS33")),

        # Connection to our SPI flash; can be used to work with the flash
        # from e.g. a bootloader.
        Resource("spi_flash", 0,
            Subsignal("sck",   Pins("N9",  dir="o")),
            Subsignal("miso",  Pins("T7",  dir="i")),
            Subsignal("mosi",  Pins("T8",  dir="o")),
            Subsignal("cs",    PinsN("N8", dir="o")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        #
        # Note: r0.1 has a DFM issue that makes it difficult to solder a BGA with
        # reliable connections on the intended SCK pin (P12), and lacks a CS pin on the
        # debug SPI; which seems like a silly omission.
        #
        # Accordingly, we're mapping the debug SPI and UART over the same pins, as the
        # microcontroller can use either.
        #

        # UART connected to the debug controller; can be routed to a host via CDC-ACM.
        Resource("uart", 0,
            Subsignal("rx",   Pins("R14", dir="i")),
            Subsignal("tx",   Pins("T14", dir="o")),
            Attrs(IO_TYPE="LVCMOS33")
        ),


        # SPI bus connected to the debug controller, for simple register exchanges.
        # Note that the Debug Controller is the master on this bus.
        Resource("debug_spi", 0,
            Subsignal("sck",  Pins( "R14", dir="i")),
            Subsignal("sdi",  Pins( "P13", dir="i")),
            Subsignal("sdo",  Pins( "P11", dir="o")),
            Subsignal("cs",   PinsN("T14", dir="i")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # FPGA-connected LEDs.
        Resource("led",  5, PinsN("P15", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led",  4, PinsN("N16", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led",  3, PinsN("M15", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led",  2, PinsN("M16", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led",  1, PinsN("L15", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led",  0, PinsN("L16", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        # USB PHYs
        ULPIResource("sideband", 
            data_sites="R2 R1 P2 P1 N1 M2 M1 L2", clk_site="R4", 
            dir_site="T3", nxt_site="T2", stp_site="T4", reset_site="R3"),
        ULPIResource("host", 
            data_sites="G2 G1 F2 F1 E1 G1 C1 B1", clk_site="K2", 
            dir_site="J1", nxt_site="H2", stp_site="J2", reset_site="K1"),
        ULPIResource("target", 
            data_sites="D16 E15 E16 F15 F16 G15 J16 K16", clk_site="B15", 
            dir_site="C15", nxt_site="C16", stp_site="B16", reset_site="G16"),

        # Target port power switching
        Resource("power_a_port",       0, Pins("C14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("pass_through_vbus",  0, Pins("D14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("target_vbus_fault",  0, Pins("K15", dir="i"), Attrs(IO_TYPE="LVCMOS33")),

        # HyperRAM (1V8 domain).
        Resource("ram",
            Subsignal("clk",   DiffPairs("B14", "A15", dir="o"), Attrs(IO_TYPE="LVCMOS18D")),
            Subsignal("dq",    Pins("A11 B10 B12 A12 B11 A10 B9 A9", dir="io")),
            Subsignal("rwds",  Pins( "A13", dir="o")),
            Subsignal("cs",    PinsN("A14", dir="o")),
            Subsignal("reset", Pins( "B13", dir="o")),
            Attrs(IO_TYPE="LVCMOS18")
        ),

        # User I/O connections.
        Resource("user_io", 0, Pins("A5", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io", 1, Pins("A4", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io", 2, Pins("A3", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("user_io", 3, Pins("A2", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
    ]

    # Neighbor headers.
    connectors = [

        # User I/O connector.
        Connector("user_io", 0, """
            A5  -  A2
            A4  -  A3
        """)

    ]

    def toolchain_prepare(self, fragment, name, **kwargs):
        overrides = {
            'ecppack_opts': '--idcode {}'.format(0x21111043)
        }
        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)


    def toolchain_program(self, products, name):
        """ Programs the relevant LUNA board via its sideband connection. """

        # Create our connection to the debug module.
        debugger = ApolloDebugger()

        # Grab our generated bitstream, and upload it to the FPGA.
        bitstream =  products.get("{}.bit".format(name))
        with JTAGChain(debugger) as jtag:
            programmer = ECP5_JTAGProgrammer(jtag)
            programmer.configure(bitstream)
