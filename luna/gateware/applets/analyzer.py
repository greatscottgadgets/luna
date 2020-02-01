#!/usr/bin/env python3
# pylint: disable=maybe-no-member
#
# This file is part of LUNA.
#
""" Generic USB analyzer backend generator for LUNA. """

import sys
import time

from nmigen import Signal, Elaboratable, Module
from nmigen.lib.cdc import FFSynchronizer

from luna.gateware.utils.cdc          import synchronize
from luna.gateware.utils              import rising_edge_detector
from luna.gateware.architecture.car   import LunaECP5DomainGenerator

from luna.gateware.interface.spi      import SPIRegisterInterface, SPIMultiplexer, SPIBus

from luna.gateware.interface.ulpi     import UMTITranslator
from luna.gateware.usb.analyzer       import USBAnalyzer

DATA_AVAILABLE  = 1
ANALYZER_RESULT = 2

class USBAnalyzerApplet(Elaboratable):
    """ Gateware that serves as a generic USB analyzer backend.

    WARNING: This is _incomplete_! It's missing:
        - a proper host interface
        - DRAM backing for analysis
    """


    def elaborate(self, platform):
        m = Module()

        # Generate our clock domains.
        clocking = LunaECP5DomainGenerator()
        m.submodules.clocking = clocking

        # Grab a reference to our debug-SPI bus.
        board_spi = synchronize(m, platform.request("debug_spi"))

        # Create our SPI-connected registers.
        m.submodules.spi_registers = spi_registers = SPIRegisterInterface(7, 8)
        m.d.comb += spi_registers.spi.connect(board_spi)

        # Create our UMTI translator.
        ulpi = platform.request("target_phy")
        m.submodules.umti = umti = UMTITranslator(ulpi=ulpi)

        # Strap our power controls to be in VBUS passthrough by default,
        # on the target port.
        m.d.comb += [
            platform.request("power_a_port")      .eq(0),
            platform.request("pass_through_vbus") .eq(1),
        ]

        # Hook up our LEDs to status signals.
        m.d.comb += [
        ]

        # Set up our parameters.
        m.d.comb += [

            # Set our mode to non-driving and full speed.
            umti.op_mode     .eq(0b01),
            umti.xcvr_select .eq(0b01),

            # Disable all of our terminations, as we want to participate in
            # passive observation.
            umti.dm_pulldown .eq(0),
            umti.dm_pulldown .eq(0),
            umti.term_select .eq(0)
        ]

        read_strobe = Signal()

        # Create a USB analyzer, and connect a register up to its output.
        m.submodules.analyzer = analyzer = USBAnalyzer(umti_interface=umti)

        # Provide registers that indicate when there's data ready, and what the result is.
        spi_registers.add_read_only_register(DATA_AVAILABLE,  read=analyzer.data_available)
        spi_registers.add_read_only_register(ANALYZER_RESULT, read=analyzer.data_out, read_strobe=read_strobe)

        m.d.comb += [

            # Internal connections.
            analyzer.next               .eq(read_strobe),

            # LED indicators.
            platform.request("led", 0)  .eq(analyzer.capturing),
            platform.request("led", 1)  .eq(analyzer.data_available),
            platform.request("led", 2)  .eq(analyzer.overrun),

            platform.request("led", 3)  .eq(umti.session_valid),
            platform.request("led", 4)  .eq(umti.rx_active),
            platform.request("led", 5)  .eq(umti.rx_error),
        ]

        # Return our elaborated module.
        return m
