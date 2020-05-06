#!/usr/bin/env python3
#
# This file is part of LUNA.
#

import os

from nmigen                         import Elaboratable, Module
from usb_protocol.emitters          import DeviceDescriptorCollection

from luna                           import top_level_cli
from luna.gateware.usb.usb2.device  import USBDevice


class USBDeviceExample(Elaboratable):
    """ Simple example of a USB device using the LUNA framework. """


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
            d.iProduct           = "Test Device"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x01
                    e.wMaxPacketSize   = 64

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x81
                    e.wMaxPacketSize   = 64

        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our USB device interface...
        ulpi = platform.request("target_phy")
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)

        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if os.getenv('LUNA_FULL_ONLY') else 0),
        ]

        # ... and for now, attach our LEDs to our most recent control request.
        m.d.comb += [
            platform.request('led', 0).eq(usb.tx_activity_led),
            platform.request('led', 1).eq(usb.rx_activity_led),
            platform.request('led', 2).eq(usb.suspended),
        ]

        return m


if __name__ == "__main__":
    top_level_cli(USBDeviceExample)
