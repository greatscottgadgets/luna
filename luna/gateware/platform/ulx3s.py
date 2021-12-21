#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" ULX3S platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable,
as appropriate:

    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_12F_Platform"
    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_25F_Platform"
    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_45F_Platform"
    > export LUNA_PLATFORM="luna.gateware.platform.ulx3s:ULX3S_85F_Platform"
"""

import os
import subprocess

from abc import ABCMeta, abstractmethod

from amaranth import *
from amaranth.build import *
import amaranth_boards.ulx3s as _ulx3s

from .core import LUNAPlatform


class ULX3SDomainGenerator(Elaboratable):
    """ Clock domain generator that creates the domain clocks for the ULX3S. """

    def elaborate(self, platform):
        m = Module()

        # Grab our default input clock.
        input_clock = platform.request(platform.default_clk, dir="i")

        # Create our domains; but don't do anything else for them, for now.
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.usb_io = ClockDomain()
        m.domains.fast   = ClockDomain()

        feedback = Signal()
        locked   = Signal()

        m.submodules.pll = Instance("EHXPLLL",
            i_RST=1,
            i_STDBY=0,
            i_CLKI=input_clock.i,
            i_PHASESEL0=0,
            i_PHASESEL1=0,
            i_PHASEDIR=1,
            i_PHASESTEP=1,
            i_PHASELOADREG=1,
            i_PLLWAKESYNC=0,
            i_ENCLKOP=0,
            i_CLKFB=feedback,

            o_LOCK=locked,
            o_CLKOP=feedback,
            o_CLKOS=ClockSignal("sync"),
            o_CLKOS2=ClockSignal("usb"),

            p_PLLRST_ENA="DISABLED",
            p_INTFB_WAKE="DISABLED",
            p_STDBY_ENABLE="DISABLED",
            p_DPHASE_SOURCE="DISABLED",
            p_OUTDIVIDER_MUXA="DIVA",
            p_OUTDIVIDER_MUXB="DIVB",
            p_OUTDIVIDER_MUXC="DIVC",
            p_OUTDIVIDER_MUXD="DIVD",
            p_CLKI_DIV=5,
            p_CLKOP_ENABLE="ENABLED",
            p_CLKOS2_ENABLE="ENABLED",
            p_CLKOP_DIV=48,
            p_CLKOP_CPHASE=9,
            p_CLKOP_FPHASE=0,
            p_CLKOS_ENABLE="ENABLED",
            p_CLKOS_DIV=10,
            p_CLKOS_CPHASE=0,
            p_CLKOS_FPHASE=0,
            p_CLKOS2_DIV=40,
            p_CLKOS2_CPHASE=0,
            p_CLKOS2_FPHASE=0,
            p_FEEDBK_PATH="CLKOP",
            p_CLKFB_DIV=2,

            a_FREQUENCY_PIN_CLKI="25",
            a_FREQUENCY_PIN_CLKOP="48",
            a_FREQUENCY_PIN_CLKOS="48",
            a_FREQUENCY_PIN_CLKOS2="12",
            a_ICP_CURRENT="12",
            a_LPF_RESISTOR="8",
            a_MFG_ENABLE_FILTEROPAMP="1",
            a_MFG_GMCREF_SEL="2",

        )

        # We'll use our 48MHz clock for everything _except_ the usb domain...
        m.d.comb += [
            ClockSignal("usb_io")  .eq(ClockSignal("sync")),
            ClockSignal("fast")    .eq(ClockSignal("sync")),

            ResetSignal("sync")    .eq(~locked),
            ResetSignal("fast")    .eq(~locked),
            ResetSignal("usb")     .eq(~locked),
            ResetSignal("usb_io")  .eq(~locked),
        ]

        return m


class ULX3S_12F_Platform(_ulx3s.ULX3S_12F_Platform, LUNAPlatform):
    name                   = "ULX3S (12F)"
    default_usb_connection = "usb"
    clock_domain_generator = ULX3SDomainGenerator


class ULX3S_25F_Platform(_ulx3s.ULX3S_25F_Platform, LUNAPlatform):
    name                   = "ULX3S (25F)"
    default_usb_connection = "usb"
    clock_domain_generator = ULX3SDomainGenerator


class ULX3S_45F_Platform(_ulx3s.ULX3S_45F_Platform, LUNAPlatform):
    name                   = "ULX3S (45F)"
    default_usb_connection = "usb"
    clock_domain_generator = ULX3SDomainGenerator


class ULX3S_85F_Platform(_ulx3s.ULX3S_85F_Platform, LUNAPlatform):
    name                   = "ULX3S (85F)"
    default_usb_connection = "usb"
    clock_domain_generator = ULX3SDomainGenerator
