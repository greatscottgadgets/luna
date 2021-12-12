#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os

from amaranth                        import Elaboratable, Module, Signal
from usb_protocol.emitters           import DeviceDescriptorCollection

from luna                            import top_level_cli
from luna.gateware.usb.usb2.device   import USBDevice
from luna.gateware.usb.usb2.endpoint import EndpointInterface


BULK_ENDPOINT_NUMBER = 1
MAX_BULK_PACKET_SIZE = 64 if os.getenv('LUNA_FULL_ONLY') else 256
CONSTANT_TO_SEND     = 0x00


class StressTestEndpoint(Elaboratable):
    """ Endpoint interface that transmits a constant to the host, without buffering.

    Attributes
    ----------
    interface: EndpointInterface
        Communications link to our USB device.


    Parameters
    ----------
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    max_packet_size: int
        The maximum packet size for this endpoint. Should match the wMaxPacketSize provided in the
        USB endpoint descriptor.
    constant: int, between 0 and 255
        The constant byte to send.
    """


    def __init__(self, *, endpoint_number: int, max_packet_size: int, constant: int):
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size
        self._constant = constant

        #
        # I/O port
        #
        self.interface = EndpointInterface()


    def elaborate(self, platform):
        m = Module()

        interface = self.interface
        tokenizer = interface.tokenizer
        tx        = interface.tx

        # Counter that stores how many bytes we have left to send.
        bytes_to_send = Signal(range(0, self._max_packet_size + 1), reset=0)

        # True iff we're the active endpoint.
        endpoint_selected = \
            tokenizer.is_in & \
            (tokenizer.endpoint == self._endpoint_number) \

        # Pulses when the host is requesting a packet from us.
        packet_requested = \
            endpoint_selected \
            & tokenizer.ready_for_response

        #
        # Transmit logic
        #

        # Schedule a packet send whenever a packet is requested.
        with m.If(packet_requested):
            m.d.usb += bytes_to_send.eq(self._max_packet_size)

        # Count a byte as send each time the PHY accepts a byte.
        with m.Elif((bytes_to_send != 0) & tx.ready):
            m.d.usb += bytes_to_send.eq(bytes_to_send - 1)

        m.d.comb += [
            # Always send our constant value.
            tx.payload .eq(self._constant),

            # Send bytes, whenever we have them.
            tx.valid   .eq(bytes_to_send != 0),
            tx.first   .eq(bytes_to_send == self._max_packet_size),
            tx.last    .eq(bytes_to_send == 1)
        ]

        #
        # Data-toggle logic
        #

        # Toggle our data pid when we get an ACK.
        with m.If(interface.handshakes_in.ack & endpoint_selected):
            m.d.usb += interface.tx_pid_toggle.eq(~interface.tx_pid_toggle)


        return m


class USBStressTest(Elaboratable):
    """ Simple device with a custom endpoint that stress tests USB hardware.

    This:
        - Uses no buffering whatsoever; every time the host requests data, we directly
          provide a constant value. This ensures that we go as fast as possible.
        - Sends a stream with maximum transition rate (all NRZI toggles).
    """

    def create_descriptors(self):
        """ Create the descriptors we want to use for our device. """

        descriptors = DeviceDescriptorCollection()

        #
        # We'll add the major components of the descriptors we we want.
        # The collection we build here will be necessary to create a standard endpoint.
        #

        # We'll need a device descriptor...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = 0x16d0
            d.idProduct          = 0xf3b

            d.iManufacturer      = "LUNA"
            d.iProduct           = "Stress Test"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = MAX_BULK_PACKET_SIZE


        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our USB device interface...
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)

        # Add our endpoint.
        test_ep = StressTestEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=MAX_BULK_PACKET_SIZE,
            constant=CONSTANT_TO_SEND
        )
        usb.add_endpoint(test_ep)


        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if os.getenv('LUNA_FULL_ONLY') else 0),
        ]


        return m


if __name__ == "__main__":
    top_level_cli(USBStressTest)
