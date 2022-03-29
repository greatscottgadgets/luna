#!/usr/bin/env python3
# pylint: disable=maybe-no-member
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Generic USB analyzer backend generator for LUNA. """

import time
import errno


import usb
from datetime import datetime
from enum import IntEnum

from amaranth                          import Signal, Elaboratable, Module
from usb_protocol.emitters             import DeviceDescriptorCollection
from usb_protocol.types                import USBRequestType

from luna.gateware.platform            import get_appropriate_platform
from luna.usb2                         import USBDevice, USBStreamInEndpoint

from luna.gateware.usb.request.control import ControlRequestHandler
from luna.gateware.usb.stream          import USBInStreamInterface
from luna.gateware.stream.generator    import StreamSerializer
from luna.gateware.utils.cdc           import synchronize
from luna.gateware.architecture.car    import LunaECP5DomainGenerator

from luna.gateware.interface.ulpi      import UTMITranslator
from luna.gateware.usb.analyzer        import USBAnalyzer


USB_SPEED_HIGH       = 0b00
USB_SPEED_FULL       = 0b01
USB_SPEED_LOW        = 0b10

USB_VENDOR_ID        = 0x1d50
USB_PRODUCT_ID       = 0x615b

BULK_ENDPOINT_NUMBER  = 1
BULK_ENDPOINT_ADDRESS = 0x80 | BULK_ENDPOINT_NUMBER
MAX_BULK_PACKET_SIZE  = 512


class USBAnalyzerState(Elaboratable):

    def __init__(self):
        self.current = Signal(8)
        self.next = Signal(8)
        self.write = Signal()

    def elaborate(self, platform):
        m = Module()
        with m.If(self.write):
            m.d.sync += self.current.eq(self.next)
        return m


class USBAnalyzerVendorRequests(IntEnum):
    GET_STATE = 0
    SET_STATE = 1


class USBAnalyzerVendorRequestHandler(ControlRequestHandler):

    def __init__(self, state):
        self.state = state
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        interface = self.interface

        # Create convenience aliases for our interface components.
        setup               = interface.setup
        handshake_generator = interface.handshakes_out

        # Transmitter for small-constant-response requests
        m.submodules.transmitter = transmitter = \
            StreamSerializer(data_length=1, domain="usb", stream_type=USBInStreamInterface, max_length_width=1)

        # Handle vendor requests
        with m.If(setup.type == USBRequestType.VENDOR):
            with m.FSM(domain="usb"):

                # IDLE -- not handling any active request
                with m.State('IDLE'):

                    # If we've received a new setup packet, handle it.
                    with m.If(setup.received):

                        # Select which vendor we're going to handle.
                        with m.Switch(setup.request):

                            with m.Case(USBAnalyzerVendorRequests.GET_STATE):
                                m.next = 'GET_STATE'
                            with m.Case(USBAnalyzerVendorRequests.SET_STATE):
                                m.next = 'SET_STATE'
                            with m.Case():
                                m.next = 'UNHANDLED'


                # GET_STATE -- Fetch the device's state
                with m.State('GET_STATE'):
                    self.handle_simple_data_request(m, transmitter, self.state.current, length=1)

                # SET_STATE -- The host is trying to set our state
                with m.State('SET_STATE'):
                    self.handle_register_write_request(m, self.state.next, self.state.write)

                # UNHANDLED -- we've received a request we're not prepared to handle
                with m.State('UNHANDLED'):

                    # When we next have an opportunity to stall, do so,
                    # and then return to idle.
                    with m.If(interface.data_requested | interface.status_requested):
                        m.d.comb += handshake_generator.stall.eq(1)
                        m.next = 'IDLE'

        return m


class USBAnalyzerApplet(Elaboratable):
    """ Gateware that serves as a generic USB analyzer backend.

    WARNING: This is _incomplete_! It's missing:
        - DRAM backing for analysis
    """


    def __init__(self, usb_speed=USB_SPEED_FULL):
        self.usb_speed = usb_speed


    def create_descriptors(self):
        """ Create the descriptors we want to use for our device. """

        descriptors = DeviceDescriptorCollection()

        #
        # We'll add the major components of the descriptors we we want.
        # The collection we build here will be necessary to create a standard endpoint.
        #

        # We'll need a device descriptor...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = USB_VENDOR_ID
            d.idProduct          = USB_PRODUCT_ID

            d.iManufacturer      = "LUNA"
            d.iProduct           = "USB Analyzer"
            d.iSerialNumber      = "[autodetect serial here]"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = BULK_ENDPOINT_ADDRESS
                    e.wMaxPacketSize   = MAX_BULK_PACKET_SIZE


        return descriptors


    def elaborate(self, platform):
        m = Module()

        # State register
        m.submodules.state = state = USBAnalyzerState()

        # Generate our clock domains.
        clocking = LunaECP5DomainGenerator()
        m.submodules.clocking = clocking

        # Create our UTMI translator.
        ulpi = platform.request("target_phy")
        m.submodules.utmi = utmi = UTMITranslator(ulpi=ulpi)

        # Strap our power controls to be in VBUS passthrough by default,
        # on the target port.
        m.d.comb += [
            platform.request("power_a_port").o      .eq(0),
            platform.request("pass_through_vbus").o .eq(1),
        ]

        # Set up our parameters.
        m.d.comb += [

            # Set our mode to non-driving and to the desired speed.
            utmi.op_mode     .eq(0b01),
            utmi.xcvr_select .eq(self.usb_speed),

            # Disable all of our terminations, as we want to participate in
            # passive observation.
            utmi.dm_pulldown .eq(0),
            utmi.dm_pulldown .eq(0),
            utmi.term_select .eq(0)
        ]

        # Create our USB uplink interface...
        uplink_ulpi = platform.request("host_phy")
        m.submodules.usb = usb = USBDevice(bus=uplink_ulpi)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        control_endpoint = usb.add_standard_control_endpoint(descriptors)

        # Add our vendor request handler to the control endpoint.
        vendor_request_handler = USBAnalyzerVendorRequestHandler(state)
        control_endpoint.add_request_handler(vendor_request_handler)

        # Add a stream endpoint to our device.
        stream_ep = USBStreamInEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_ep)

        # Create a USB analyzer, and connect a register up to its output.
        m.submodules.analyzer = analyzer = USBAnalyzer(utmi_interface=utmi)

        m.d.comb += [
            # Connect enable signal to host-controlled state register.
            analyzer.capture_enable     .eq(state.current[0]),

            # Flush endpoint when analyzer is idle with capture disabled.
            stream_ep.flush             .eq(analyzer.idle & ~analyzer.capture_enable),

            # USB stream uplink.
            stream_ep.stream            .stream_eq(analyzer.stream),

            usb.connect                 .eq(1),

            # LED indicators.
            platform.request("led", 0).o  .eq(analyzer.capturing),
            platform.request("led", 1).o  .eq(analyzer.stream.valid),
            platform.request("led", 2).o  .eq(analyzer.overrun),

            platform.request("led", 3).o  .eq(utmi.session_valid),
            platform.request("led", 4).o  .eq(utmi.rx_active),
            platform.request("led", 5).o  .eq(utmi.rx_error),
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

        self._buffer = bytearray()
        self._device = None



    def build_and_configure(self, capture_speed):
        """ Builds the LUNA analyzer applet and configures the FPGA with it. """

        # Create the USBAnalyzer we want to work with.
        analyzer = USBAnalyzerApplet(usb_speed=capture_speed)

        # Build and upload the analyzer.
        # FIXME: use a temporary build directory
        platform = get_appropriate_platform()
        platform.build(analyzer, do_program=True)

        time.sleep(3)

        # For now, we'll use a slow, synchronous connection to the device via pyusb.
        # This should be replaced with libusb1 for performance.
        end_time = time.time() + 6
        while not self._device:
            if time.time() > end_time:
                raise RuntimeError('Timeout! The analyzer device did not show up.')

            self._device = usb.core.find(idVendor=USB_VENDOR_ID, idProduct=USB_PRODUCT_ID)


    def _fetch_data_into_buffer(self):
        """ Attempts a single data read from the analyzer into our buffer. """

        try:
            data = self._device.read(BULK_ENDPOINT_ADDRESS, MAX_BULK_PACKET_SIZE)
            self._buffer.extend(data)
        except usb.core.USBError as e:
            if e.errno == errno.ETIMEDOUT:
                pass
            else:
                raise



    def read_raw_packet(self):
        """ Reads a raw packet from our USB Analyzer. Blocks until a packet is complete.

        Returns: packet, timestamp, flags:
            packet    -- The raw packet data, as bytes.
            timestamp -- The timestamp at which the packet was taken, in microseconds.
            flags     -- Flags indicating connection status. Format TBD.
        """

        size = 0
        packet = None

        # Read until we get enough data to determine our packet's size...
        while not packet:
            while len(self._buffer) < 3:
                self._fetch_data_into_buffer()

            # Extract our size from our buffer.
            size = (self._buffer.pop(0) << 8) | self._buffer.pop(0)

            # ... and read until we have a packet.
            while len(self._buffer) < size:
                self._fetch_data_into_buffer()

            # Extract our raw packet...
            packet = self._buffer[0:size]
            del self._buffer[0:size]


        # ... and return it.
        # TODO: extract and provide status flags
        # TODO: generate a timestamp on-device
        return packet, datetime.now(), None
