#
# This file is part of LUNA.
#
# Copyright (c) 2020 Marian Sauer
# SPDX-License-Identifier: BSD-3-Clause

""" Numato Opsis platform definitions.

This is a non-core platform. To use it, you'll need to set your LUNA_PLATFORM variable:

    > export LUNA_PLATFORM="luna.gateware.platform.numato_opsis:NumatoOpsisPlatform"
"""

from nmigen import *
from nmigen.build import *
from nmigen.vendor.xilinx_spartan_3_6 import XilinxSpartan6Platform

from nmigen_boards.resources import *
from .core import LUNAPlatform

__all__ = ["NumatoOpsisPlatform"]

class NumatoOpsisClockDomainGenerator(Elaboratable):
    """ NumatoOpsis clock domain generator.
        Generate 60 MHz for ULPI phy in clock input operation.

    """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        m.domains.sync                  = ClockDomain()
        m.domains.feedback_out          = ClockDomain()
        m.domains.feedback              = ClockDomain()
        m.domains.usb_pll_local         = ClockDomain()
        m.domains.usb_pll_local_shifted = ClockDomain()
        m.domains.usb                   = ClockDomain()
        m.domains.usb_shifted           = ClockDomain()
        m.domains.fast                  = ClockDomain()

        forward_ulpi_clk = platform.request("forward_ulpi_clk", 0, dir='o', xdr=2)

        usb2_locked   = Signal()

        # Note: this is a setting that worked for the board used in bringup, does
        # not mean it is a good setting for all process/voltage/temperature variations

        # ToDo: measure real timing with oscilloscope
        m.submodules.usb2_pll = Instance("PLL_BASE",
            # generic
            p_BANDWIDTH             = "OPTIMIZED",
            p_CLK_FEEDBACK          = "CLKFBOUT",
            p_COMPENSATION          = "SYSTEM_SYNCHRONOUS",
            p_DIVCLK_DIVIDE         = 5,
            p_CLKFBOUT_MULT         = 24,
            p_CLKFBOUT_PHASE        = 0.000,
            p_CLKOUT0_DIVIDE        = 8,
            p_CLKOUT0_PHASE         = 0.000,
            p_CLKOUT0_DUTY_CYCLE    = 0.500,
            p_CLKOUT1_DIVIDE        = 8,
            p_CLKOUT1_PHASE         = 101.000,
            p_CLKOUT1_DUTY_CYCLE    = 0.500,
            p_CLKIN_PERIOD          = 10.000,
            p_REF_JITTER            = 0.010,
            # ports
            o_CLKFBOUT              = ClockSignal("feedback_out"),
            o_CLKOUT0               = ClockSignal("usb_pll_local"),
            o_CLKOUT1               = ClockSignal("usb_pll_local_shifted"),
            o_CLKOUT2               = Signal(1),
            o_CLKOUT3               = Signal(1),
            o_CLKOUT4               = Signal(1),
            o_CLKOUT5               = Signal(1),
            o_LOCKED                = usb2_locked,
            i_RST                   = 0,
            i_CLKFBIN               = ClockSignal("feedback"),
            i_CLKIN                 = ClockSignal("fast"),
        )

        m.submodules.feedback_bufg = Instance("BUFG",
            i_I = ClockSignal("feedback_out"),
            o_O = ClockSignal("feedback")
        )

        m.submodules.usb_bufg = Instance("BUFG",
            i_I = ClockSignal("usb_pll_local"),
            o_O = ClockSignal("usb")
        )

        m.submodules.usb_shifted_bufg = Instance("BUFG",
            i_I = ClockSignal("usb_pll_local_shifted"),
            o_O = ClockSignal("usb_shifted")
        )

        # bring up ULPI clock
        #debug_clk = platform.request("debug_header", 2, dir='o', xdr=2)

        m.d.comb += [
            #debug_clk.o_clk       .eq(ClockSignal("usb")),
            #debug_clk.o0          .eq(0),
            #debug_clk.o1          .eq(1),
            forward_ulpi_clk.o_clk .eq(ClockSignal("usb_shifted")),
            forward_ulpi_clk.o0    .eq(0),
            forward_ulpi_clk.o1    .eq(1),
            ClockSignal("sync")    .eq(ClockSignal("usb")),
            ClockSignal("fast")    .eq(platform.request("clk_100MHz")),
            ResetSignal("usb")     .eq(~usb2_locked),
            ResetSignal("sync")    .eq(~usb2_locked),
            ResetSignal("fast")    .eq(~usb2_locked)
        ]

        return m

def ULPIResource(name, data_sites, clk_site, dir_site, nxt_site, stp_site, reset_site):
    """ Generates a set of resources for a ULPI-connected USB PHY. """

    return Resource(name, 0,
        Subsignal("data",  Pins(data_sites,  dir="io")),
        Subsignal("clk",   Pins(clk_site,    dir="i" )),
        Subsignal("dir",   Pins(dir_site,    dir="i" )),
        Subsignal("nxt",   Pins(nxt_site,    dir="i" )),
        Subsignal("stp",   Pins(stp_site,    dir="o" )),
        Subsignal("rst",   PinsN(reset_site, dir="o" )),
        Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")
    )

class NumatoOpsisPlatform(XilinxSpartan6Platform, LUNAPlatform):
    """ Board description for NumatoOpsis. """

    name                   = "NumatoOpsis"

    device                 = "xc6slx45t"
    package                = "fgg484"
    speed                  = "3"

    clock_domain_generator = NumatoOpsisClockDomainGenerator
    default_usb_connection = "ulpi"
    ulpi_handle_clocking = False

    resources = [

        # Clock
        Resource("clk_100MHz", 0, Pins("AB13", dir="i"), Clock(100e6), Attrs(IOSTANDARD="LVCMOS33")),

        # Button
        *ButtonResources(pins="Y3", attrs=Attrs(IOSTANDARD="LVCMOS15", PULLUP="TRUE")),

        # ULPI phy with input clock operation (ULPI clk generated by link)
        ULPIResource("ulpi",
            data_sites="Y14 W14 Y18 W17 AA14 AB14 Y16 W15", clk_site="-",
            dir_site="W13", nxt_site="V13", stp_site="W18", reset_site="V17",
        ),

        Resource("forward_ulpi_clk", 0, Pins("Y13", dir="o"), Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")),
        Resource("debug_header", 0, Pins("P28_0:SD_DAT1", dir="o"), Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")),
        Resource("debug_header", 1, Pins("P28_0:SD_DAT0", dir="o"), Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")),
        Resource("debug_header", 2, Pins("P28_0:SD_CLK", dir="o"), Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")),
        Resource("debug_header", 3, Pins("P28_0:SD_CMD", dir="o"), Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")),
        Resource("debug_header", 4, Pins("P28_0:SD_DAT3", dir="o"), Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")),
        Resource("debug_header", 5, Pins("P28_0:SD_DAT2", dir="o"), Attrs(IOSTANDARD="LVCMOS33", SLEW="FAST")),

    ]

    connectors = [
        Connector("P28", 0, {
            "SD_DAT1" : "AB4",
            "SD_DAT0" : "AA4",
            "SD_CLK"  : "T7",
            "SD_CMD"  : "U6",
            "SD_DAT3" : "Y5",
            "SD_DAT2" : "AB5",
            } # IOSTANDARD=LVCMOS33
        ),

    ]

    def toolchain_prepare(self, fragment, name, **kwargs):
        # Note: this is a setting that worked for the board used in bringup, does
        # not mean it is a good setting for all process/voltage/temperature variations

        # ToDo: input timing is not met according to timing report but it works,
        # measure real timing with oscilloscope
        extra_constraints = [

            "NET \"ulpi_0__data__io<0>\" TNM = ulpi;",
            "NET \"ulpi_0__data__io<1>\" TNM = ulpi;",
            "NET \"ulpi_0__data__io<2>\" TNM = ulpi;",
            "NET \"ulpi_0__data__io<3>\" TNM = ulpi;",
            "NET \"ulpi_0__data__io<4>\" TNM = ulpi;",
            "NET \"ulpi_0__data__io<5>\" TNM = ulpi;",
            "NET \"ulpi_0__data__io<6>\" TNM = ulpi;",
            "NET \"ulpi_0__data__io<7>\" TNM = ulpi;",
            "NET \"forward_ulpi_clk_0__io\" TNM = ulpi;",
            "NET \"ulpi_0__dir__io\"  TNM = ulpi;",
            "NET \"ulpi_0__nxt__io\"  TNM = ulpi;",
            "NET \"ulpi_0__stp__io\"  TNM = ulpi;",
            "TIMEGRP \"ulpi\" OFFSET = OUT AFTER \"clk_100MHz_0__io\" REFERENCE_PIN \"forward_ulpi_clk_0__io\" RISING;",
            "TIMEGRP \"ulpi\" OFFSET = IN 3 ns VALID 9 ns BEFORE \"clk_100MHz_0__io\" RISING;",

        ]

        overrides = { "add_constraints": "\n".join(extra_constraints) }
        return super().toolchain_prepare(fragment, name, **overrides, **kwargs)

    def toolchain_program(self, products, name):
        pass
