#!/usr/bin/env python3
# pylint: disable=maybe-no-member
#
# This file is part of LUNA.
#
""" Generic USB analyzer backend generator for LUNA. """

import sys
import time
from datetime import datetime

from nmigen import Signal, Elaboratable, Module

from luna                             import get_appropriate_platform

from luna.gateware.utils.cdc          import synchronize
from luna.gateware.architecture.car   import LunaECP5DomainGenerator

from luna.gateware.interface.ulpi     import UMTITranslator
from luna.gateware.usb.analyzer       import USBAnalyzer

# Temporary.
from luna.apollo                      import ApolloDebugger, ApolloILAFrontend
from luna.gateware.interface.spi      import SPIRegisterInterface, SPIMultiplexer, SPIBus



DATA_AVAILABLE  = 1
ANALYZER_RESULT = 2

USB_SPEED_HIGH = 0b00
USB_SPEED_FULL = 0b01
USB_SPEED_LOW  = 0b10


class USBAnalyzerApplet(Elaboratable):
    """ Gateware that serves as a generic USB analyzer backend.

    WARNING: This is _incomplete_! It's missing:
        - a proper host interface
        - DRAM backing for analysis
    """

    def __init__(self, usb_speed=USB_SPEED_FULL):
        self.usb_speed = usb_speed


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

        # Set up our parameters.
        m.d.comb += [

            # Set our mode to non-driving and to the desired speed.
            umti.op_mode     .eq(0b01),
            umti.xcvr_select .eq(self.usb_speed),

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



class USBAnalyzerConnection:
    """ Class representing a connection to a LUNA USB analyzer.

    This abstracts away connection details, so we can rapidly change the way things
    work without requiring changes in e.g. our ViewSB frontend.
    """

    def __init__(self):
        """ Creates our connection to the USBAnalyzer. """

        # For now, we'll connect to the target via the Apollo debug controller.
        # This should be replaced by a high-speed USB link soon; but for now
        # we'll use the slow debug connection.
        self._debugger = ApolloDebugger()


    def build_and_configure(self, capture_speed):
        """ Builds the LUNA analyzer applet and configures the FPGA with it. """

        # Create the USBAnalyzer we want to work with.
        analyzer = USBAnalyzerApplet(usb_speed=capture_speed)

        # Build and upload the analyzer.
        # FIXME: use a temporary build directory
        platform = get_appropriate_platform()
        platform.build(analyzer, do_program=True)


    def _data_is_available(self):
        return self._debugger.spi.register_read(DATA_AVAILABLE)

    def _read_byte(self):
        return self._debugger.spi.register_read(ANALYZER_RESULT)

    def _get_next_byte(self):
        while not self._data_is_available():
            time.sleep(0.1)

        return self._read_byte()


    def read_raw_packet(self):
        """ Reads a raw packet from our USB Analyzer. Blocks until a packet is complete.

        Returns: packet, timestamp, flags:
            packet    -- The raw packet data, as bytes.
            timestamp -- The timestamp at which the packet was taken, in microseconds.
            flags     -- Flags indicating connection status. Format TBD.
        """

        # Read our two-byte header from the debugger...
        size = (self._get_next_byte() << 16) | self._get_next_byte()

        # ... and read our packet.
        packet = bytearray([self._get_next_byte() for _ in range(size)])

        # Return our packet.
        # TODO: extract and provide status flags
        # TODO: generate a timestamp on-device
        return packet, datetime.now(), None
