#
# This file is part of LUNA.
#
""" OpenViszla platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.openvizsla:OpenVizsla
"""

from nmigen import Elaboratable, ClockDomain, Module
from nmigen.build import Resource, Subsignal, Pins, PinsN, Attrs, Clock
from nmigen.vendor.xilinx_spartan_3_6 import XilinxSpartan6Platform

__all__ = ["OpenVizsla"]

def ULPIResource(name, data_sites, clk_site, dir_site, nxt_site, stp_site, reset_site, extras=()):
    """ Generates a set of resources for a ULPI-connected USB PHY. """

    return Resource(name, 0,
        Subsignal("data",  Pins(data_sites,  dir="io")),
        Subsignal("clk",   Pins(clk_site,    dir="i" ), Attrs(PULLDOWN="TRUE"), Clock(60e6)),
        Subsignal("dir",   Pins(dir_site,    dir="i" )),
        Subsignal("nxt",   Pins(nxt_site,    dir="i" )),
        Subsignal("stp",   Pins(stp_site,    dir="o" )),
        Subsignal("rst",   PinsN(reset_site, dir="o" )),
        Attrs(SLEW="FAST")
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


class OpenVizsla(XilinxSpartan6Platform):
    """ Board description for OpenVizsla USB analyzer. """

    name        = "OpenVizsla"

    device      = "xc6slx9"
    package     = "tqg144"
    speed       = "3"

    default_clk = "clk_12MHz"

    # Provide the type that'll be used to create our clock domains.
    clock_domain_generator = StubClockDomainGenerator

    #
    # I/O resources.
    #
    resources   = [

        # Clocks.
        Resource("clk_12MHz", 0, Pins("P50", dir="i"), Clock(12e6), Attrs(IOSTANDARD="LVCMOS33")),

        # User button.
        Resource("btn", 0, Pins("P67", dir="i"), Attrs(IOSTANDARD="LVCMOS33")),

        # User LEDs.
        Resource("led", 0, Pins("P57", dir="o"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("led", 1, Pins("P58", dir="o"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("led", 2, Pins("P59", dir="o"), Attrs(IOSTANDARD="LVCMOS33")),

        # Core ULPI PHY.
        ULPIResource("target_phy",
            data_sites="P120 P119 P118 P117 P116 P115 P114 P112", clk_site="P123",
            dir_site="P124", nxt_site="P121", stp_site="P126", reset_site="P127",
        ),

        # Extra pins that the OpenVizsla calls the "spare" pins.
        Resource("spare", 2, Pins("P102"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 3, Pins("P101"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 4, Pins("P100"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 5, Pins("P99"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 6, Pins("P98"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 7, Pins("P97"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 8, Pins("P95"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 9, Pins("P94"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 10, Pins("P93"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 11, Pins("P92"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 12, Pins("P88"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 13, Pins("P87"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 14, Pins("P85"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 15, Pins("P84"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 16, Pins("P83"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 17, Pins("P82"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 18, Pins("P81"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 19, Pins("P80"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 20, Pins("P79"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 21, Pins("P78"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 22, Pins("P75"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("spare", 23, Pins("P74"), Attrs(IOSTANDARD="LVCMOS33")),

        # FTDI FIFO connection.
        Resource("ftdi", 0,
            Subsignal("clk", Pins("P51")),
            Subsignal("d", Pins("P65 P62 P61 P46 P45 P44 P43 P48")),
            Subsignal("rxf_n", Pins("P55")),
            Subsignal("txe_n", Pins("P70")),
            Subsignal("rd_n", Pins("P41")),
            Subsignal("wr_n", Pins("P40")),
            Subsignal("siwua_n", Pins("P66")),
            Subsignal("oe_n", Pins("P38")),
            Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")
        ),
    ]

    # TODO: detail the Spare connector here?
    connectors = []


    def toolchain_program(self, products, name):
        """ Programs the OpenVizsla's FPGA. """

        try:
            from openvizsla       import OVDevice
            from openvizsla.libov import HW_Init
        except ImportError:
            raise ImportError("pyopenvizsla is required to program OpenVizsla boards")

        # Connect to our OpenVizsla...
        device = OVDevice()
        failed = device.ftdi.open()
        if failed:
            raise IOError("Could not connect to OpenVizsla!")

        # ... and pass it our bitstream.
        try:
            with products.extract(f"{name}.bit") as bitstream_file:
                HW_Init(device.ftdi, bitstream_file.encode('ascii'))
        finally:
            device.ftdi.close()
