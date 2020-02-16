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

from luna.gateware.interface.ulpi     import UTMITranslator
from luna.gateware.usb.analyzer       import USBAnalyzer

# Temporary.
from luna.apollo                      import ApolloDebugger
from luna.gateware.interface.uart     import UARTTransmitter



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

    _BAUD_RATE = 115200 * 4

    def __init__(self, usb_speed=USB_SPEED_FULL):
        self.usb_speed = usb_speed


    def elaborate(self, platform):
        m = Module()

        # Generate our clock domains.
        clocking = LunaECP5DomainGenerator()
        m.submodules.clocking = clocking

        # Create our UTMI translator.
        ulpi = platform.request("target_phy")
        m.submodules.umti = umti = UTMITranslator(ulpi=ulpi)

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

        # Create our UART uplink.
        uart = platform.request("uart")
        clock_freq = platform.DEFAULT_CLOCK_FREQUENCIES_MHZ['sync'] * 1000000

        transmitter = UARTTransmitter(divisor=clock_freq // self._BAUD_RATE)
        m.submodules.transmitter = transmitter

        # Create a USB analyzer, and connect a register up to its output.
        m.submodules.analyzer = analyzer = USBAnalyzer(umti_interface=umti)

        m.d.comb += [

            # UART uplink
            uart.tx                     .eq(transmitter.tx),

            # Internal connections.
            transmitter.data            .eq(analyzer.data_out),
            transmitter.send            .eq(analyzer.data_available),
            analyzer.next               .eq(transmitter.accepted),

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

    @staticmethod
    def _find_serial_connection():
        """ Attempts to find a serial connection to the USB analyzer. """
        import serial.tools.list_ports

        # Generate a search string including our VID/PID.
        vid_pid = f"{ApolloDebugger.VENDOR_ID:04x}:{ApolloDebugger.PRODUCT_ID:04x}"

        for port in serial.tools.list_ports.grep(vid_pid):
            return serial.Serial(port.device, USBAnalyzerApplet._BAUD_RATE)

        raise IOError("could not find a debug connection!")


    def __init__(self):
        """ Creates our connection to the USBAnalyzer. """

        # For now, we'll connect to the target via the Apollo debug controller.
        # This should be replaced by a high-speed USB link soon; but for now
        # we'll use the slow debug connection.
        self._debugger = ApolloDebugger()
        self._serial   = self._find_serial_connection()


    def build_and_configure(self, capture_speed):
        """ Builds the LUNA analyzer applet and configures the FPGA with it. """

        # Create the USBAnalyzer we want to work with.
        analyzer = USBAnalyzerApplet(usb_speed=capture_speed)

        # Build and upload the analyzer.
        # FIXME: use a temporary build directory
        platform = get_appropriate_platform()
        platform.build(analyzer, do_program=True)

        self._serial.flush()

    def _get_next_byte(self):
        datum = self._serial.read(1)
        return datum[0]


    def read_raw_packet(self):
        """ Reads a raw packet from our USB Analyzer. Blocks until a packet is complete.

        Returns: packet, timestamp, flags:
            packet    -- The raw packet data, as bytes.
            timestamp -- The timestamp at which the packet was taken, in microseconds.
            flags     -- Flags indicating connection status. Format TBD.
        """

        size = 0

        # Read our two-byte header from the debugger...
        while not size:
            size = (self._get_next_byte() << 16) | self._get_next_byte()

        # ... and read our packet.
        packet = bytearray([self._get_next_byte() for _ in range(size)])

        # Return our packet.
        # TODO: extract and provide status flags
        # TODO: generate a timestamp on-device
        return packet, datetime.now(), None
