#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" OpenViszla platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.openvizsla:OpenVizslaPlatform
"""

from amaranth import *
from amaranth.build import *
from amaranth.vendor.xilinx_spartan_3_6 import XilinxSpartan6Platform

from amaranth_boards.resources import *
from .core import LUNAPlatform

__all__ = ["OpenVizslaPlatform"]

class OpenVizslaClockDomainGenerator(Elaboratable):
    """ OpenVizsla clock domain generator.
        Assumes the ULPI PHY will be providing a USB clock.

    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains; but don't do anything else for them, for now.
        m.domains.sync = ClockDomain()
        m.domains.usb  = ClockDomain()
        m.domains.fast = ClockDomain()

        m.d.comb += [
            ClockSignal("sync")  .eq(ClockSignal("usb")),
            ClockSignal("fast")  .eq(ClockSignal("usb"))
        ]

        return m


class OpenVizslaPlatform(XilinxSpartan6Platform, LUNAPlatform):
    """ Board description for OpenVizsla USB analyzer. """

    name                   = "OpenVizsla"

    device                 = "xc6slx9"
    package                = "tqg144"
    speed                  = "3"
    default_clk            = "clk_12MHz"

    clock_domain_generator = OpenVizslaClockDomainGenerator
    default_usb_connection = "target_phy"

    #
    # I/O resources.
    #
    resources   = [

        # Clocks.
        Resource("clk_12MHz", 0, Pins("P50", dir="i"), Clock(12e6), Attrs(IOSTANDARD="LVCMOS33")),

        # Buttons / LEDs.
        *ButtonResources(pins="P67", attrs=Attrs(IOSTANDARD="LVCMOS33")),
        *LEDResources(pins="P57 P58 P59", attrs=Attrs(IOSTANDARD="LVCMOS33")),

        # Core ULPI PHY.
        ULPIResource("target_phy", 0,
            data="P120 P119 P118 P117 P116 P115 P114 P112", clk="P123",
            dir="P124", nxt="P121", stp="P126", rst="P127", rst_invert=True,
            attrs=Attrs(IOSTANDARD="LVCMOS33")
        ),


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

        # Trigger in/out pins.
        Resource("trigger_in",  0, Pins("P75"), Attrs(IOSTANDARD="LVCMOS33")),
        Resource("trigger_out", 0, Pins("P74"), Attrs(IOSTANDARD="LVCMOS33")),
    ]

    connectors = [
        Connector("spare", 0,
            "-   -   P102 P101 P100 P99 P98 P97 P95 P94 P93 P92" # continued
            "P88 P87 P85 P84  P83  P82  P81 P80 P79 P78 P75 P74"
        )
    ]

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
