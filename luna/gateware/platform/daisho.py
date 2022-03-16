#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Daisho platform definitions. """

import os
import subprocess

from amaranth import *
from amaranth.build import *
from amaranth.vendor.intel import IntelPlatform

from amaranth_boards.resources import *

from .core import LUNAPlatform
from ..architecture.car import PHYResetController


__all__ = ["DaishoPlatform"]


class DaishoClockAndResetController(Elaboratable):
    """ Controller for Daisho's clocking and global resets. """

    def elaborate(self, platform):
        m = Module()

        # Standard LUNA domains.
        m.domains.usb     = ClockDomain()
        m.domains.fast    = ClockDomain()

        # LUNA USB3 clock domains.
        m.domains.pipe_rx    = ClockDomain()
        m.domains.pipe_tx    = ClockDomain()
        m.domains.pipe_io_tx = ClockDomain()
        m.domains.pipe_io_rx = ClockDomain()

        # Reset controller for the PHY.
        m.submodules.usb_reset = usb_reset = PHYResetController()

        locked = Signal()
        clk_bad = Signal()


        #
        # USB3 domain PLL.
        #

        # Our PLL uses a single output to represent each of its clocks.
        # We'll create a composite signal to assign, here.
        clk_62M5        = Signal()
        composite_clock = Cat(
            clk_62M5,                   # quarter rate clock                            (62.5MHz)
            ClockSignal("pipe_rx"),     # post-DDR half-rate clock                      (125MHz)
            ClockSignal("pipe_tx"),     # post-DDR half-rate clock, shifted 90-degrees  (125MHz)
            Signal(),                   # pre-DDR full-rate clock                       (250MHz)
            ClockSignal("pipe_io_tx")   # pre-DDR full-rate clock, shifted 90-degrees   (250MHz)
        )

        # PLL for our USB3 domains.
        m.submodules.pll = Instance("ALTPLL",
            # PLL configuration parameters; copied from the Daisho USB3 Core.
            p_bandwidth_type = "AUTO",
            p_clk0_divide_by = 4,
            p_clk0_duty_cycle = 50,
            p_clk0_multiply_by = 1,
            p_clk0_phase_shift = "0",
            p_clk1_divide_by = 2,
            p_clk1_duty_cycle = 50,
            p_clk1_multiply_by = 1,
            p_clk1_phase_shift = "0",
            p_clk2_divide_by = 2,
            p_clk2_duty_cycle = 50,
            p_clk2_multiply_by = 1,
            p_clk2_phase_shift = "4889",
            p_clk3_divide_by = 1,
            p_clk3_duty_cycle = 50,
            p_clk3_multiply_by = 1,
            p_clk3_phase_shift = "0",
            p_clk4_divide_by = 1,
            p_gate_lock_signal="YES",
            p_clk4_duty_cycle = 50,
            p_clk4_multiply_by = 1,
            p_clk4_phase_shift = "2000",
            p_compensate_clock = "CLK1",
            p_inclk0_input_frequency = 4000,
            p_intended_device_family = "Cyclone IV E",
            p_lpm_hint = "CBX_MODULE_PREFIX=mf_usb3_pll",
            p_lpm_type = "altpll",
            p_operation_mode = "NORMAL",
            p_pll_type = "AUTO",
            p_port_activeclock = "PORT_UNUSED",
            p_port_areset = "PORT_UNUSED",
            p_port_clkbad0 = "PORT_USED",
            p_port_clkbad1 = "PORT_UNUSED",
            p_port_clkloss = "PORT_UNUSED",
            p_port_clkswitch = "PORT_UNUSED",
            p_port_configupdate = "PORT_UNUSED",
            p_port_fbin = "PORT_UNUSED",
            p_port_inclk0 = "PORT_USED",
            p_port_inclk1 = "PORT_UNUSED",
            p_port_locked = "PORT_USED",
            p_port_pfdena = "PORT_UNUSED",
            p_port_phasecounterselect = "PORT_UNUSED",
            p_port_phasedone = "PORT_UNUSED",
            p_port_phasestep = "PORT_UNUSED",
            p_port_phaseupdown = "PORT_UNUSED",
            p_port_pllena = "PORT_UNUSED",
            p_port_scanaclr = "PORT_UNUSED",
            p_port_scanclk = "PORT_UNUSED",
            p_port_scanclkena = "PORT_UNUSED",
            p_port_scandata = "PORT_UNUSED",
            p_port_scandataout = "PORT_UNUSED",
            p_port_scandone = "PORT_UNUSED",
            p_port_scanread = "PORT_UNUSED",
            p_port_scanwrite = "PORT_UNUSED",
            p_port_clk0 = "PORT_USED",
            p_port_clk1 = "PORT_USED",
            p_port_clk2 = "PORT_USED",
            p_port_clk3 = "PORT_USED",
            p_port_clk4 = "PORT_USED",
            p_port_clk5 = "PORT_UNUSED",
            p_port_clkena0 = "PORT_UNUSED",
            p_port_clkena1 = "PORT_UNUSED",
            p_port_clkena2 = "PORT_UNUSED",
            p_port_clkena3 = "PORT_UNUSED",
            p_port_clkena4 = "PORT_UNUSED",
            p_port_clkena5 = "PORT_UNUSED",
            p_port_extclk0 = "PORT_UNUSED",
            p_port_extclk1 = "PORT_UNUSED",
            p_port_extclk2 = "PORT_UNUSED",
            p_port_extclk3 = "PORT_UNUSED",
            p_self_reset_on_loss_lock = "ON",
            p_width_clock = 5,

            # Drive our clock from the I/O domain, which is typically set from the PHY's PCLK.
            i_inclk = ClockSignal("pipe_io_rx"),

            # Grab all of our output clocks in one go.
            o_clk    = composite_clock,
            o_locked = locked,
        )


        m.d.comb += [
            ResetSignal("usb")    .eq(usb_reset.phy_reset),
            ClockSignal("fast")   .eq(ClockSignal("sync")),

            ResetSignal("pipe_rx")      .eq(clk_bad),
            ResetSignal("pipe_tx")      .eq(clk_bad),
            ResetSignal("pipe_io_tx")   .eq(clk_bad),

        ]

        return m


    def stretch_sync_strobe_to_usb(self, m, strobe, output=None, allow_delay=False):
        """
        Helper that stretches a strobe from the `sync` domain to communicate with the `usb` domain.
        Works for any chosen frequency in which f(usb) < f(sync).
        """
        m.d.comb += output.eq(strobe)



class DaishoPlatform(IntelPlatform, LUNAPlatform):
    """ Board description for Daisho boards."""

    name        = "Daisho"
    device      = "EP4CE30"
    package     = "F29"
    speed       = "C8"

    # Boundary scan register is 1632 wide.

    default_clk = "clk_50MHz"
    clock_domain_generator = DaishoClockAndResetController
    default_usb_connection = "ulpi"

    # The TI1310A requires strap values to be present on ULPI DATA{4, 5, 6, 7}
    # during PHY startup. We'll provide these strap values here.
    # Their meaning:
    # - bit 7:    0, do not disable the PIPE PHY by default ("PHY isolation")
    # - bit 6:    0, use single-data-rate ULPI
    # - bit 5/4: 11, use 40MHz crystal oscillator
    phy_data_straps = 0b0011_0000
    ignore_phy_vbus = True


    #
    # I/O resources.
    #
    resources   = [

        # Primary clock generator clocks.
        Resource("clk_50MHz", 0, Pins("AG14", dir="i"), Clock(50e6), Attrs(IO_STANDARD="1.8V")),

        #
        # Mainboard PHYs
        #

        # USB2 / ULPI section of the TUSB1310A.
        ULPIResource("ulpi", 0,
            data="K1 K2 L2 L1 M2 M1 P2 P1",
            clk="J1", dir="L3", nxt="G1", stp="J3",
            attrs=Attrs(IO_STANDARD="1.8 V", CURRENT_STRENGTH_NEW="8MA", SLEW_RATE="2")
        ),
        # USB3 / ULPI section of the TUSB1310A.
        Resource("pipe", 0,
            # Transmit bus.
            Subsignal("tx_clk",         Pins("AC1",         dir="o")),
            Subsignal("tx_data",        Pins("R3 R1 R2 T3 U1 V1 U2 V2 W2 W1 AB2 AB1 AD1 AD2 AE1 AF2", dir="o")),
            Subsignal("tx_data_k",      Pins("AC2 AE2",     dir="o")),

            # Transmit config.
            Subsignal("tx_elecidle",    Pins("M4",          dir="o" )),
            Subsignal("tx_detrx_lpbk",  Pins("K4",          dir="o" )),
            Subsignal("tx_oneszeros",   Pins("M3",          dir="o" )),
            Subsignal("tx_deemph",      Pins("AA5 AA7",     dir="o" )),
            Subsignal("tx_margin",      Pins("K3 H3 G4",    dir="o" )),
            Subsignal("tx_swing",       Pins("L4",          dir="o" )),

            # Receive bus.
            Subsignal("pclk",           Pins("Y2",          dir="i"), Clock(250e6)),
            Subsignal("rx_data",        Pins("T4 U3 U4 V4 V3 W4 W3 Y4 Y3 AB3 AC4 AA3 AD3 AE4 AF3 AE3", dir="i")),
            Subsignal("rx_data_k",      Pins("AC3 AD4",     dir="i")),

            # Receive status/config.
            Subsignal("rx_status",      Pins("AA6 Y6 V7",   dir="i" )),
            Subsignal("rx_elecidle",    Pins("R6",          dir="io")),
            Subsignal("rx_polarity",    Pins("AC5",         dir="o" )),
            Subsignal("rx_termination", Pins("U5",          dir="o" )),
            Subsignal("rx_valid",       Pins("R4",          dir="i" )),

            # Control and status.
            Subsignal("reset",          PinsN("AB6",        dir="o" )),
            Subsignal("phy_reset",      PinsN("N4",         dir="o" )),
            Subsignal("power_down",     Pins("R7 R5",       dir="o" )),
            Subsignal("phy_status",     Pins("V5",          dir="io")),
            Subsignal("power_present",  Pins("AB5",         dir="i" )),
            Subsignal("rate",           Pins("N3",          dir="o" )),
            Subsignal("elas_buf_mode",  Pins("AD5",         dir="o" )),
            Subsignal("out_enable",     Pins("G3",          dir="o" )),

            # Attributes
            Attrs(IO_STANDARD="1.8V")
        ),

        #
        # Daughterboard Interfaces
        #
        Resource("io_expander", 0,
            Subsignal("scl",   Pins("M23",  dir="io" )),
            Subsignal("sda",   Pins("L23",  dir="io" )),
            Subsignal("reset", PinsN("L23", dir="o"  )),
            Subsignal("int",   PinsN("L26", dir="o"  )),
        ),


        #
        # USB Daughterboard PHYs
        #
        ULPIResource("ulpi", 1,
            data="F27 K28 G28 F28 E28 D27 D28 C27",
            clk="J27", dir="F26", nxt="L28", stp="H26",
            attrs=Attrs(IO_STANDARD="1.8 V", CURRENT_STRENGTH_NEW="12MA", SLEW_RATE="2")
        ),
        # USB3 / ULPI section of the TUSB1310A.
        Resource("pipe", 1,
            # Transmit bus.
            Subsignal("tx_clk",         Pins("B25",         dir="o")),
            Subsignal("tx_data",        Pins("E22 C25 C24 D23 C23 D21 C22 C20 D20 C19 A26 B26 B23 A23 B22 B21", dir="o")),
            Subsignal("tx_data_k",      Pins("A25 A22",     dir="o")),

            # Transmit config.
            Subsignal("tx_elecidle",    Pins("D26",         dir="o" )),
            Subsignal("tx_detrx_lpbk",  Pins("E25",         dir="o" )),
            #Subsignal("tx_oneszeros",   Pins("M3",          dir="o" )),
            Subsignal("tx_deemph",      Pins("G25 G26",     dir="o" )),
            Subsignal("tx_margin",      Pins("J26 J25 K26", dir="o" )),
            Subsignal("tx_swing",       Pins("E26",         dir="o" )),

            # Receive bus.
            Subsignal("pclk",           Pins("B15",         dir="i"), Clock(250e6)),
            Subsignal("rx_data",        Pins("B19 G21 A19 B18 A18 D15 C16 C18 D16 B17 D18 A17 C21 F21 E17 E21", dir="i")),
            Subsignal("rx_data_k",      Pins("D19 C15",     dir="i")),

            # Receive status/config.
            Subsignal("rx_status",      Pins("G23 M24 L25", dir="i" )),
            Subsignal("rx_elecidle",    Pins("J23",         dir="io")),
            Subsignal("rx_polarity",    Pins("L24",         dir="o" )),
            Subsignal("rx_termination", Pins("H23",         dir="o" )),
            Subsignal("rx_valid",       Pins("A21",         dir="i" )),

            # Control and status.
            #Subsignal("reset",          PinsN("AB6",        dir="o" )),
            Subsignal("phy_reset",      PinsN("N4",         dir="o" )),
            Subsignal("power_down",     Pins("R7 R5",       dir="o" )),
            Subsignal("phy_status",     Pins("V5",          dir="io")),
            Subsignal("power_present",  Pins("AB5",         dir="i" )),
            Subsignal("rate",           Pins("N3",          dir="o" )),
            Subsignal("elas_buf_mode",  Pins("AD5",         dir="o" )),
            Subsignal("out_enable",     Pins("G3",          dir="o" )),

            # Attributes
            Attrs(IO_STANDARD="1.8V")
        ),





        ULPIResource("ulpi", 2,
            data="E12 F12 C8 E8 E11 E14 E7 E10",
            clk="A15", dir="H16", nxt="J17", stp="G24",
            attrs=Attrs(IO_STANDARD="1.8 V", CURRENT_STRENGTH_NEW="12MA", SLEW_RATE="2")
        ),


        # SPI bus connected to the debug controller, for simple register exchanges.
        # Note that the Debug Controller is the controller on this bus.
        Resource("debug_spi", 0,
            Subsignal("sck",  Pins( "R26", dir="i")),
            Subsignal("sdi",  Pins( "R28", dir="i")),
            Subsignal("sdo",  Pins( "R27", dir="o")),
            Subsignal("cs",   PinsN("R25", dir="i")),
            Attrs(IO_STANDARD="1.8 V")
        ),

        # This is a probably-temporary set of LED resources located on the SODIMM
        # connector. This exists because:
        #  - The Daisho board has no FPGA-controlled LEDs, but "debug adapters" exist
        #    with LEDs on each line of the SODIMMs.
        #  - There are so few boards in existence that I don't think this is going to be
        #    a problem.
        *LEDResources(
            pins=
                "Y26  AB27 AB26 Y24  AB28 V25  AC27 AC28 W27 W28  T25      "  # Row 1
                "AB24 AD26 AD26 AE28 AE25 AE21 W26  U28  V28 AD27 AD28 AF27", # Row 2
            attrs=Attrs(IO_STANDARD="1.8 V"))
    ]

    connectors  = []

    @property
    def file_templates(self):
        # Set our Cyclone-III configuration scheme to avoid an I/IO bank conflict.
        templates = super().file_templates
        templates["{{name}}.qsf"] += r"""
            set_global_assignment -name OPTIMIZATION_MODE "Aggressive Performance"
            set_global_assignment -name FITTER_EFFORT "Standard Fit"
            set_global_assignment -name PHYSICAL_SYNTHESIS_EFFORT "Extra"
            set_global_assignment -name CYCLONEIII_CONFIGURATION_SCHEME "PASSIVE SERIAL"
            set_global_assignment -name ON_CHIP_BITSTREAM_DECOMPRESSION OFF
            set_instance_assignment -name DECREASE_INPUT_DELAY_TO_INPUT_REGISTER OFF -to *ulpi*
            set_instance_assignment -name INCREASE_DELAY_TO_OUTPUT_PIN OFF -to *ulpi*
        """
        templates["{{name}}.sdc"] += r"""
            derive_pll_clocks
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

        from apollo_fpga import ApolloDebugger
        from apollo_fpga.intel import IntelJTAGProgrammer

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
