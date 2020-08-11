#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Daisho platform definitions. """

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

        m.domains.sync = ClockDomain()
        m.domains.usb  = ClockDomain("usb")
        m.domains.fast = ClockDomain("fast")

        m.d.comb += [
            ClockSignal("sync")  .eq(ulpi.clk),
            ClockSignal("usb")   .eq(ClockSignal("sync")),
            ClockSignal("fast")  .eq(ClockSignal("sync")),
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
            clk="J1", dir="L3", nxt="G1", stp="J3", rst_invert=True,
            attrs=Attrs(IO_STANDARD="1.8 V")
        ),

        # HACK: pretend the SODIMM slot is user I/O
        Resource("user_io", 0, Pins("U28"), Attrs(IO_STANDARD="1.8V")),
        Resource("user_io", 1, Pins("V28"), Attrs(IO_STANDARD="1.8V")),
        Resource("user_io", 2, Pins("W28"), Attrs(IO_STANDARD="1.8V")),
        Resource("user_io", 3, Pins("W27"), Attrs(IO_STANDARD="1.8V")),
    ]

    connectors  = []

    @property
    def file_templates(self):
        # Set our Cyclone-III configuration scheme to avoid an I/IO bank conflict.
        templates = super().file_templates
        templates["{{name}}.qsf"] += r"""
            set_global_assignment -name CYCLONEIII_CONFIGURATION_SCHEME "PASSIVE SERIAL"
        """
        return templates
