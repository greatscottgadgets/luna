#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
"""
The DE0 Nano does not have an explicit USB port. Instead, you'll need to connect an external ULPI PHY breakout,
such as https://www.waveshare.com/wiki/USB3300_USB_HS_Board.

See the pin definitions below for connection information (ULPIResource).

The DE0 Nano is an -unsupported- platform! To use it, you'll need to set your LUNA_PLATFORM variable:
    > export LUNA_PLATFORM="luna.gateware.platform.de0_nano:DE0NanoPlatform"
"""    

import os
import logging
import subprocess

from amaranth import *
from amaranth.build import *
from amaranth.vendor.intel import IntelPlatform

from amaranth_boards.resources import *

from .core import LUNAPlatform
from ..architecture.car import PHYResetController


__all__ = ["DE0NanoPlatform"]


class DE0NanoClockAndResetController(Elaboratable):
    """ Controller for de0_nano's clocking and global resets. """
    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        pass

    def elaborate(self, platform):
        m = Module()

        # Create our domains; but don't do anything else for them, for now.
        m.domains.sync = ClockDomain()
        m.domains.usb  = ClockDomain()
        m.domains.fast = ClockDomain()

        main_clock = Signal()
        locked = Signal()

        m.submodules.pll = Instance("ALTPLL",
            p_BANDWIDTH_TYPE         = "AUTO",
            p_CLK0_DIVIDE_BY         = 1,
            p_CLK0_DUTY_CYCLE        = 50,
            p_CLK0_MULTIPLY_BY       = 1,
            p_CLK0_PHASE_SHIFT       = 0,
            p_INCLK0_INPUT_FREQUENCY = 16666,
            p_OPERATION_MODE         = "NORMAL",

            # Drive our clock from the USB clock
            # coming from the USB clock pin of the USB3300
            i_inclk  = ClockSignal("usb"),
            o_clk    = main_clock,
            o_locked = locked,
        )

        m.d.comb += [
            ClockSignal("sync").eq(main_clock),
            ClockSignal("fast").eq(main_clock)
        ]

        # Use a blinky to see if the clock signal works
        # from amaranth_boards.test.blinky import Blinky
        # m.submodules += Blinky()

        return m

class DE0NanoPlatform(IntelPlatform, LUNAPlatform):
    """ This is a de0_nano board with an USB3300 PHY attached to JP_2 """

    name        = "de0_nano"
    device      = "EP4CE22"
    package     = "F17"
    speed       = "C6"

    default_clk = "clk_50MHz"
    clock_domain_generator = DE0NanoClockAndResetController
    default_usb_connection = "ulpi"
    ignore_phy_vbus = True

    def __init__(self, *args, **kwargs):
        logging.warning("This platform is not officially supported, and thus not tested. Your results may vary.")
        logging.warning("Note also that this platform does not use the DE0 nano's main USB port!")
        logging.warning("You'll need to connect a ULPI PHY breakout. See the platform file for more info.")

        super().__init__(*args, **kwargs)

    #
    # I/O resources.
    #
    resources = [
        # Primary clock generator clocks.
        Resource("clk_50MHz", 0, Pins("R8", dir="i"), Clock(50e6), Attrs(io_standard="3.3-V LVTTL")),

        # USB2 / ULPI section of the USB3300.
        ULPIResource("ulpi", 0,
            data="JP_2:27 JP_2:25 JP_2:23 JP_2:21 JP_2:19 JP_2:17 JP_2:15 JP_2:13",
            clk="JP_2:1", # this needs to be a clock pin of the FPGA or the core won't work
            dir="JP_2:18", nxt="JP_2:16", stp="JP_2:14", rst="JP_2:22",
            attrs=Attrs(io_standard="3.3-V LVCMOS")
        ),

        UARTResource(0,
            # GND on JP1 Pin 12.
            rx="JP_1:8", tx="JP_1:10",
            attrs=Attrs(io_standard="3.3-V LVTTL")),

        *LEDResources(
            pins="A15 A13 B13 A11 D1 F3 B1 L3",
            attrs=Attrs(io_standard="3.3-V LVTTL")),

        *ButtonResources(
            pins="J15 E1", invert=True,
            attrs=Attrs(io_standard="3.3-V LVTTL")),

        *SwitchResources(
            pins="M1 T8 B9 M15",
            attrs=Attrs(io_standard="3.3-V LVTTL")),

        SDRAMResource(0,
            clk="R4", cke="L7", cs_n="P6", we_n="C2", ras_n="L2", cas_n="L1",
            ba="M7 M6", a="P2 N5 N6 M8 P8 T7 N8 T6 R1 P1 N2 N1 L4",
            dq="G2 G1 L8 K5 K2 J2 J1 R7 T4 T2 T3 R3 R5 P3 N3 K1", dqm="R6 T5",
            attrs=Attrs(io_standard="3.3-V LVTTL")),

        # Accelerometer
        Resource("acc", 0,
            Subsignal("cs_n", Pins("G5", dir="o")),
            Subsignal("int",  Pins("M2", dir="i")),
            Attrs(io_standard="3.3-V LVTTL")),
        # I2C is part of the Accelerometer
        I2CResource(0,
            scl="F2", sda="F1",
            attrs=Attrs(io_standard="3.3-V LVTTL")),

        # ADC
        Resource("adc", 0,
            Subsignal("cs_n",  Pins("A10")),
            Subsignal("saddr", Pins("B10")),
            Subsignal("sclk",  Pins("B14")),
            Subsignal("sdat",  Pins("A9")),
            Attrs(io_standard="3.3-V LVTTL")),

        # ECPS
        Resource("epcs", 0,
            Subsignal("data0", Pins("H2")),
            Subsignal("dclk",  Pins("H1")),
            Subsignal("ncs0",  Pins("D2")),
            Subsignal("asd0",  Pins("C1")),
            Attrs(io_standard="3.3-V LVTTL")),
    ]

    connectors = [
        # PIN               1  2   3   4   5   6   7   8   9   10  11  12  13  14  15  16  17  18 19 20  21  22  23  24  25  26  27  28 29 30 31  32  33  34  35  36  37  38  39  40
        Connector("JP", 1, "A8 D3  B8  C3  A2  A3  B3  B4  A4  B5  -   -   A5  D5  B6  A6  B7  D6 A7 C6  C8  E6  E7  D8  E8  F8  F9  E9  - -  C9  D9  E11 E10 C11 B11 A12 D11 D12 B12"),
        Connector("JP", 2, "T9 F13 R9  T15 T14 T13 R13 T12 R12 T11 -   -   T10 R11 P11 R10 N12 P9 N9 N11 L16 K16 R16 L15 P15 P16 R14 N16 - -  N15 P14 L14 N14 M10 L13 J16 K15 J13 J14"),
        Connector("JP", 3, "-  E15 E16 M16 A14 B16 C14 C16 C15 D16 D15 D14 F15 F16 F14 G16 G15 -  -  -   -   -   -   -   -   -")
    ]

    @property
    def file_templates(self):
        templates = super().file_templates
        templates["{{name}}.qsf"] += r"""
            set_global_assignment -name OPTIMIZATION_MODE "Aggressive Performance"
            set_global_assignment -name FITTER_EFFORT "Standard Fit"
            set_global_assignment -name PHYSICAL_SYNTHESIS_EFFORT "Extra"
            set_instance_assignment -name DECREASE_INPUT_DELAY_TO_INPUT_REGISTER OFF -to *ulpi*
            set_instance_assignment -name INCREASE_DELAY_TO_OUTPUT_PIN OFF -to *ulpi*
            set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL
        """
        templates["{{name}}.sdc"] += r"""
            create_clock -name "clk_60MHz" -period 16.667 [get_ports "ulpi_0__clk__io"]
        """
        return templates


    def toolchain_program(self, products, name):
        """ Programs the attached de0_nano board via a Quartus programming cable. """

        quartus_pgm = os.environ.get("QUARTUS_PGM", "quartus_pgm")
        with products.extract("{}.sof".format(name)) as bitstream_filename:
            subprocess.check_call([quartus_pgm, "--haltcc", "--mode", "JTAG",
                                   "--operation", "P;" + bitstream_filename])
