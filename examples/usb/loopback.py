#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os

from amaranth                import Elaboratable, Module, Cat

from usb_protocol.emitters   import DeviceDescriptorCollection

from luna                    import top_level_cli
from luna.usb2               import USBDevice, USBStreamOutEndpoint, USBStreamInEndpoint


class USBStreamOutDeviceExample(Elaboratable):
    """ Simple device that demonstrates use of a bulk-OUT endpoint.

    Captures streaming data, and outputs it over the User I/O.
    """

    BULK_ENDPOINT_NUMBER = 1
    MAX_BULK_PACKET_SIZE = 512

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
            d.iProduct           = "User IO streamer"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = self.BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.MAX_BULK_PACKET_SIZE

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | self.BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.MAX_BULK_PACKET_SIZE


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

        # Add a stream endpoint to our device.
        stream_out_ep = USBStreamOutEndpoint(
            endpoint_number=self.BULK_ENDPOINT_NUMBER,
            max_packet_size=self.MAX_BULK_PACKET_SIZE,
        )
        usb.add_endpoint(stream_out_ep)

        # Add a stream endpoint to our device.
        stream_in_ep = USBStreamInEndpoint(
            endpoint_number=self.BULK_ENDPOINT_NUMBER,
            max_packet_size=self.MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_in_ep)

        # Connect our endpoints together.
        stream_in = stream_in_ep.stream
        stream_out = stream_out_ep.stream

        m.d.comb += [
            stream_in.payload           .eq(stream_out.payload),
            stream_in.valid             .eq(stream_out.valid),
            stream_in.first             .eq(stream_out.first),
            stream_in.last              .eq(stream_out.last),
            stream_out.ready            .eq(stream_in.ready),

            usb.connect                 .eq(1)
        ]

        return m


if __name__ == "__main__":
    top_level_cli(USBStreamOutDeviceExample)
