#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os

from amaranth                import Elaboratable, Module, Signal
from usb_protocol.emitters   import DeviceDescriptorCollection

from luna                    import top_level_cli
from luna.usb2               import USBDevice, USBStreamInEndpoint


class USBCounterDeviceExample(Elaboratable):
    """ Simple device that demonstrates use of a bulk-IN endpoint.

    Always sends a monotonically-incrementing 8-bit counter up to the host.
    This is useful for two things:

    - We can get a sense that no bytes are dropped by observing the counter sequence.
    - This generates data with a maximum possible rate; which is useful for gauging LUNA throughput.
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
            d.iProduct           = "Counter/Throughput Test"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

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
        stream_ep = USBStreamInEndpoint(
            endpoint_number=self.BULK_ENDPOINT_NUMBER,
            max_packet_size=self.MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_ep)

        # Always generate a monotonic count for our stream, which counts every time our
        # stream endpoint accepts a data byte.
        counter = Signal(8)
        with m.If(stream_ep.stream.ready):
            m.d.usb += counter.eq(counter + 1)

        m.d.comb += [
            stream_ep.stream.valid    .eq(1),
            stream_ep.stream.payload  .eq(counter)
        ]


        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if os.getenv('LUNA_FULL_ONLY') else 0),
        ]


        return m


if __name__ == "__main__":
    top_level_cli(USBCounterDeviceExample)
