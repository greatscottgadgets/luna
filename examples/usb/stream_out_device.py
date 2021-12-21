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
from luna.usb2               import USBDevice, USBStreamOutEndpoint
from luna.gateware.platform  import NullPin


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
        stream_ep = USBStreamOutEndpoint(
            endpoint_number=self.BULK_ENDPOINT_NUMBER,
            max_packet_size=self.MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_ep)

        leds    = Cat(platform.request_optional("led", i, default=NullPin()) for i in range(6))
        user_io = Cat(platform.request_optional("user_io", i, default=NullPin()) for i in range(4))

        # Always stream our USB data directly onto our User I/O and LEDS.
        with m.If(stream_ep.stream.valid):
            m.d.usb += [
                leds     .eq(stream_ep.stream.payload),
                user_io  .eq(stream_ep.stream.payload),
            ]

        # Always accept data as it comes in.
        m.d.comb += stream_ep.stream.ready.eq(1)


        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if os.getenv('LUNA_FULL_ONLY') else 0),
        ]


        return m


if __name__ == "__main__":
    top_level_cli(USBStreamOutDeviceExample)
