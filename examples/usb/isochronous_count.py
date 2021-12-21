#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os

from amaranth                import Elaboratable, Module, Signal
from usb_protocol.types      import USBTransferType
from usb_protocol.emitters   import DeviceDescriptorCollection

from luna                    import top_level_cli
from luna.usb2               import USBDevice, USBIsochronousInEndpoint


class USBIsochronousCounterDeviceExample(Elaboratable):
    """ Simple device that demonstrates use of an isochronous-IN endpoint.

    Always sends a monotonically-incrementing 8-bit counter up to the host; but does so
    using an isochronous endpoint. In this case, the counter stands in for a simple memory.
    """

    ISO_ENDPOINT_NUMBER      = 1
    MAX_ISO_PACKET_SIZE      = 1024
    TRANSFERS_PER_MICROFRAME = (2 << 11)

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
            d.iProduct           = "Isochronous IN Test"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bmAttributes     = USBTransferType.ISOCHRONOUS
                    e.bEndpointAddress = 0x80 | self.ISO_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.TRANSFERS_PER_MICROFRAME | self.MAX_ISO_PACKET_SIZE
                    e.bInterval        = 1


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
        iso_ep = USBIsochronousInEndpoint(
            endpoint_number=self.ISO_ENDPOINT_NUMBER,
            max_packet_size=self.MAX_ISO_PACKET_SIZE
        )
        usb.add_endpoint(iso_ep)

        # We'll tie our address directly to our value, ensuring that we always
        # count as each offset is increased.
        m.d.comb += [
            iso_ep.bytes_in_frame.eq(self.MAX_ISO_PACKET_SIZE * 3),
            iso_ep.value.eq(iso_ep.address)
        ]

        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if os.getenv('LUNA_FULL_ONLY') else 0),
        ]


        return m


if __name__ == "__main__":
    top_level_cli(USBIsochronousCounterDeviceExample)
