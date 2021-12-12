#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os

from amaranth                       import Elaboratable, Module, Signal
from usb_protocol.types             import USBTransferType
from usb_protocol.emitters          import DeviceDescriptorCollection

from luna                           import top_level_cli
from luna.usb2                      import USBDevice, USBSignalInEndpoint



class USBInterruptExample(Elaboratable):
    """ Simple example of a USB device that presents an interrupt endpoint.

    This demonstrates use of the ``USBSignalInEndpoint``, which reports the value
    of a status signal when polled. Here, we'll create a 32-bit counter, and report
    its value each time our interrupt endpoint is polled.

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
            d.iProduct           = "Status interrupt mechanism"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                # Single in endpoint, EP1/IN.
                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x81
                    e.wMaxPacketSize   = 64
                    e.bmAttributes     = USBTransferType.INTERRUPT

                    # Request that we be polled once ber microseconds (2 ^ 3 microframes).
                    e.bInterval        = 4


        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create the 32-bit counter we'll be using as our status signal.
        counter = Signal(32)
        m.d.usb += counter.eq(counter + 1)

        # Create our USB device interface...
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)

        # Create an interrupt endpoint which will carry the value of our counter to the host
        # each time our interrupt EP is polled.
        status_ep = USBSignalInEndpoint(width=32, endpoint_number=1, endianness="big")
        usb.add_endpoint(status_ep)
        m.d.comb += status_ep.signal.eq(counter)


        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if os.getenv('LUNA_FULL_ONLY') else 0),
        ]

        return m


if __name__ == "__main__":
    top_level_cli(USBInterruptExample)
