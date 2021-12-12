
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" TinyFPGA Platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.tinyfpga:TinyFPGABxPlatform"
"""

import os
import subprocess

from amaranth import Elaboratable, ClockDomain, Module, ClockSignal, Instance, Signal, Const, ResetSignal
from amaranth.build import Resource, Subsignal, Pins, Attrs, Clock, Connector, PinsN
from amaranth_boards.tinyfpga_bx import TinyFPGABXPlatform as _TinyFPGABXPlatform

from .core import LUNAPlatform


class TinyFPGABxDomainGenerator(Elaboratable):
    """ Creates clock domains for the TinyFPGA Bx. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()
        locked = Signal()

        # Create our domains...
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        # ... create our 48 MHz IO and 12 MHz USB clock...
        clk48  = Signal()
        clk12  = Signal()
        m.submodules.pll = Instance("SB_PLL40_2F_CORE",
            i_REFERENCECLK  = platform.request(platform.default_clk),
            i_RESETB        = Const(1),
            i_BYPASS        = Const(0),

            o_PLLOUTCOREA   = clk48,
            o_PLLOUTCOREB   = clk12,
            o_LOCK          = locked,

            # Create a 48 MHz PLL clock...
            p_FEEDBACK_PATH = "SIMPLE",
            p_PLLOUT_SELECT_PORTA = "GENCLK",
            p_PLLOUT_SELECT_PORTB = "SHIFTREG_0deg",
            p_DIVR          = 0,
            p_DIVF          = 47,
            p_DIVQ          = 4,
            p_FILTER_RANGE  = 1,
        )

        # ... and constrain them to their new frequencies.
        platform.add_clock_constraint(clk48, 48e6)
        platform.add_clock_constraint(clk12, 12e6)

        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb")     .eq(clk12),
            ClockSignal("sync")    .eq(clk48),
            ClockSignal("usb_io")  .eq(clk48),
            ClockSignal("fast")    .eq(clk48),

            ResetSignal("usb")     .eq(~locked),
            ResetSignal("sync")    .eq(~locked),
            ResetSignal("usb_io")  .eq(~locked),
            ResetSignal("fast")    .eq(~locked)
        ]

        return m


class TinyFPGABxPlatform(_TinyFPGABXPlatform, LUNAPlatform):
    name                   = "TinyFPGA Bx"
    clock_domain_generator = TinyFPGABxDomainGenerator
    default_usb_connection = "usb"
