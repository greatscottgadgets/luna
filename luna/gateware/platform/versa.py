#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" ECP5 Versa platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.versa:ECP5Versa_5G_Platform"
"""

from nmigen import *
from nmigen.build import *
from nmigen.vendor.lattice_ecp5 import LatticeECP5Platform

from nmigen_boards.versa_ecp5_5g import VersaECP55GPlatform as _VersaECP55G

from .core import LUNAPlatform

__all__ = ["ECP5Versa_5G_Platform"]


class VersaDomainGenerator(Elaboratable):
    """ Clock generator for ECP5 Versa boards. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains.
        m.domains.ss     = ClockDomain()
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.fast   = ClockDomain()


        # Grab our clock and global reset signals.
        clk100 = platform.request(platform.default_clk)
        reset  = platform.request(platform.default_rst)

        # Generate the clocks we need for running our SerDes.
        feedback = Signal()
        locked   = Signal()
        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=clk100,

                # Generated clock outputs.
                o_CLKOP=feedback,
                o_CLKOS= ClockSignal("sync"),
                o_CLKOS2=ClockSignal("fast"),

                # Status.
                o_LOCK=locked,

                # PLL parameters...
                p_PLLRST_ENA="DISABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_CLKOS3_FPHASE=0,
                p_CLKOS3_CPHASE=0,
                p_CLKOS2_FPHASE=0,
                p_CLKOS2_CPHASE=5,
                p_CLKOS_FPHASE=0,
                p_CLKOS_CPHASE=5,
                p_CLKOP_FPHASE=0,
                p_CLKOP_CPHASE=5,
                p_PLL_LOCK_MODE=0,
                p_CLKOS_TRIM_DELAY="0",
                p_CLKOS_TRIM_POL="FALLING",
                p_CLKOP_TRIM_DELAY="0",
                p_CLKOP_TRIM_POL="FALLING",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKOS3_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXC="DIVC",
                p_CLKOS2_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXB="DIVB",
                p_CLKOS_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOS3_DIV=1,
                p_CLKOS2_DIV=5,
                p_CLKOS_DIV=8,
                p_CLKOP_DIV=10,
                p_CLKFB_DIV=1,
                p_CLKI_DIV=1,
                p_FEEDBK_PATH="CLKOP",

                # Internal feedback.
                i_CLKFB=feedback,

                # Control signals.
                i_RST=reset,
                i_PHASESEL0=0,
                i_PHASESEL1=0,
                i_PHASEDIR=1,
                i_PHASESTEP=1,
                i_PHASELOADREG=1,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS=0,
                i_ENCLKOS2=0,
                i_ENCLKOS3=0,

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI  ="100.000000",
                a_FREQUENCY_PIN_CLKOS ="100.000000",
                a_FREQUENCY_PIN_CLKOP ="200.000000",
                a_FREQUENCY_PIN_CLKOP2="200.000000",
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8"
        )

        # Control our resets.
        m.d.comb += [
            ClockSignal("ss")      .eq(ClockSignal("sync")),

            ResetSignal("ss")      .eq(~locked),
            ResetSignal("sync")    .eq(~locked),
            ResetSignal("usb")     .eq(~locked),
            ResetSignal("fast")    .eq(~locked),
        ]

        return m


class ECP5Versa_5G_Platform(_VersaECP55G, LUNAPlatform):
    name                   = "ECP5 Versa 5G"

    clock_domain_generator = VersaDomainGenerator
    default_usb_connection = None

    additional_resources = [
        Resource("serdes", 1,
            Subsignal("rx", DiffPairs("Y5", "Y6")),
            Subsignal("tx", DiffPairs("W4", "W5"))
        ),

        Resource("user_io", 0, Pins("A8"), Attrs(IO_TYPE="LVCMOS33")),
    ]

    # Create our semantic aliases.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_resources(self.additional_resources)
