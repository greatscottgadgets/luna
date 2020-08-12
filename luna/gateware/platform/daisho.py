#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Daisho platform definitions. """

import os
import subprocess

from nmigen import *
from nmigen.build import *
from nmigen.vendor.intel import IntelPlatform

from nmigen_boards.resources import *

from .core import LUNAPlatform


__all__ = ["DaishoPlatform"]


class DaishoDomainGenerator(Elaboratable):
    """ Clock domain generator that creates the domain clocks for the ULX3S. """

    def elaborate(self, platform):
        m = Module()

        ulpi = platform.request("ulpi")
        m.d.comb += ClockSignal("usb").eq(ulpi.clk)

        m.domains.sync = ClockDomain()
        m.domains.usb  = ClockDomain("usb")
        m.domains.fast = ClockDomain("fast")

        m.d.comb += [
            ClockSignal("sync")   .eq(ClockSignal("usb")),
            ClockSignal("fast")   .eq(ClockSignal("usb")),
        ]

        # HAX: Temporarily strap the USB PHY to enabled, while we're using its clock.
        m.d.comb += [
            platform.request("usb_out_enable").o  .eq(1),
            platform.request("usb_phy_reset").o   .eq(0)
        ]

        return m


class DaishoPlatform(IntelPlatform, LUNAPlatform):
    """ Board description for Daisho boards."""

    name        = "Daisho"
    device      = "EP4CE30"
    package     = "F29"
    speed       = "C8"

    #default_clk = "clk_60MHz"
    clock_domain_generator = DaishoDomainGenerator
    default_usb_connection = "ulpi"


    #
    # I/O resources.
    #
    resources   = [

        # USB2 section of the TUSB1310A.
        ULPIResource("ulpi", 0,
            data="K1 K2 L2 L1 M2 M1 P2 P1",
            clk="J1", dir="L3", nxt="G1", stp="J3", rst="N4", rst_invert=True,
            attrs=Attrs(IO_STANDARD="1.8 V")
        ),

        # Control signals for the TUSB1310A.
        Resource("usb_out_enable", 0, Pins("G3",  dir="o"), Attrs(IO_STANDARD="1.8 V")),
        Resource("usb_phy_reset", 0, PinsN("AB6", dir="o"), Attrs(IO_STANDARD="1.8 V")),
    ]

    connectors  = []

    @property
    def file_templates(self):
        # Set our Cyclone-III configuration scheme to avoid an I/IO bank conflict.
        templates = super().file_templates
        templates["{{name}}.qsf"] += r"""
            set_global_assignment -name CYCLONEIII_CONFIGURATION_SCHEME "PASSIVE SERIAL"
            set_global_assignment -name ON_CHIP_BITSTREAM_DECOMPRESSION OFF
        """
        return templates


    def _toolchain_program_quartus(self, products, name):
        """ Programs the attached Daisho board via a Quartus programming cable. """

        quartus_pgm = os.environ.get("QUARTUS_PGM", "quartus_pgm")
        with products.extract("{}.sof".format(name)) as bitstream_filename:
            subprocess.check_call([quartus_pgm, "--haltcc", "--mode", "JTAG",
                                   "--operation", "P;" + bitstream_filename])


    def toolchain_program(self, products, name):
        """ Programs the relevant Daisho board via its sideband connection. """

        from luna.apollo import ApolloDebugger
        from luna.apollo.intel import IntelJTAGProgrammer

        # If the user has opted to use their own programming cable, use it instead.
        if os.environ.get("PROGRAM_WITH_QUARTUS", False):
            self._toolchain_program_quartus(products, name)
            return

        # Create our connection to the debug module.
        debugger = ApolloDebugger()

        # Grab our generated bitstream, and upload it to the FPGA.
        bitstream =  products.get("{}.rbf".format(name))
        with debugger.jtag as jtag:
            programmer = IntelJTAGProgrammer(jtag)
            programmer.configure(bitstream)
