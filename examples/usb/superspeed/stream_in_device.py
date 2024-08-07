#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020-2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth import *

from usb_protocol.emitters         import SuperSpeedDeviceDescriptorCollection

from luna                          import top_level_cli
from luna.gateware.platform        import NullPin
from luna.gateware.usb.devices.ila import USBIntegratedLogicAnalyer, USBIntegratedLogicAnalyzerFrontend

from luna.usb3                     import USBSuperSpeedDevice, SuperSpeedStreamInEndpoint


class USBSuperSpeedExample(Elaboratable):
    """ Simple example of a USB SuperSpeed device using the LUNA framework. """

    BULK_ENDPOINT_NUMBER = 1
    MAX_BULK_PACKET_SIZE = 1024

    def create_descriptors(self):
        """ Create the descriptors we want to use for our device. """

        descriptors = SuperSpeedDeviceDescriptorCollection()

        #
        # We'll add the major components of the descriptors we we want.
        # The collection we build here will be necessary to create a standard endpoint.
        #

        # We'll need a device descriptor...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = 0x1209
            d.idProduct          = 0x0001

            # We're complying with the USB 3.2 standard.
            d.bcdUSB             = 3.2

            # USB3 requires this to be "9", to indicate 2 ** 9, or 512B.
            d.bMaxPacketSize0    = 9

            d.iManufacturer      = "LUNA"
            d.iProduct           = "SuperSpeed Bulk Test"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:
            c.bMaxPower        = 50

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor(add_default_superspeed=True) as e:
                    e.bEndpointAddress = 0x80 | self.BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.MAX_BULK_PACKET_SIZE

        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our core PIPE PHY. Since PHY configuration is per-board, we'll just ask
        # our platform for a pre-configured USB3 PHY.
        m.submodules.phy = phy = platform.create_usb3_phy()

        # Create our core SuperSpeed device.
        m.submodules.usb = usb = USBSuperSpeedDevice(phy=phy)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)

        # Create our example bulk endpoint.
        stream_in_ep = SuperSpeedStreamInEndpoint(
            endpoint_number=self.BULK_ENDPOINT_NUMBER,
            max_packet_size=self.MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_in_ep)

        # Create a simple, monotonically-increasing data stream, and connect that up to
        # to our streaming endpoint.
        counter   = Signal(16)
        stream_in = stream_in_ep.stream

        # Always provide our counter as the input to our stream; it will be consumed
        # whenever our stream endpoint can accept it.
        m.d.comb += [
            stream_in.data    .eq(counter),
            stream_in.valid   .eq(0b1111)
        ]

        # Increment our counter whenever our endpoint is accepting data.
        with m.If(stream_in.ready):
            m.d.ss += counter.eq(counter + 1)


        # Return our elaborated module.
        return m


if __name__ == "__main__":
    top_level_cli(USBSuperSpeedExample)
