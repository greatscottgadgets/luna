#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth                       import Elaboratable, Module, Cat
from usb_protocol.types             import USBRequestType
from usb_protocol.emitters          import DeviceDescriptorCollection

from luna                           import top_level_cli
from luna.gateware.platform         import NullPin
from luna.gateware.usb.usb2.device  import USBDevice
from luna.gateware.usb.usb2.request import USBRequestHandler


class LEDRequestHandler(USBRequestHandler):
    """ Simple, example request handler that can control the board's LEDs. """

    REQUEST_SET_LEDS = 0

    def elaborate(self, platform):
        m = Module()

        interface         = self.interface
        setup             = self.interface.setup

        # Grab a reference to the board's LEDs.
        leds  = Cat(platform.request_optional("led", i, default=NullPin()).o for i in range(8))

        #
        # Vendor request handlers.

        with m.If(setup.type == USBRequestType.VENDOR):
            with m.Switch(setup.request):

                # SET_LEDS request handler: handler that sets the board's LEDS
                # to a user provided value
                with m.Case(self.REQUEST_SET_LEDS):

                    # If we have an active data byte, splat it onto the LEDs.
                    #
                    # For simplicity of this example, we'll accept any byte in
                    # the packet; and not just the first one; each byte will
                    # cause an update. This is fun; we can PWM the LEDs with
                    # USB packets. :)
                    with m.If(interface.rx.valid & interface.rx.next):
                        m.d.usb += leds.eq(interface.rx.payload)

                    # Once the receive is complete, respond with an ACK.
                    with m.If(interface.rx_ready_for_response):
                        m.d.comb += interface.handshakes_out.ack.eq(1)

                    # If we reach the status stage, send a ZLP.
                    with m.If(interface.status_requested):
                        m.d.comb += self.send_zlp()


                with m.Case():

                    #
                    # Stall unhandled requests.
                    #
                    with m.If(interface.status_requested | interface.data_requested):
                        m.d.comb += interface.handshakes_out.stall.eq(1)

                return m



class USBVendorDeviceExample(Elaboratable):
    """ Simple example of a device that operates via vendor requests.

    Sets LEDs to the value set in vendor request 0.
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
            d.iProduct           = "Fancy USB-Controlled LEDs"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x01
                    e.wMaxPacketSize   = 64

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
        control_ep = usb.add_standard_control_endpoint(descriptors)

        # Add our custom request handlers.
        control_ep.add_request_handler(LEDRequestHandler())

        # Connect our device by default.
        m.d.comb += usb.connect.eq(1)


        return m


if __name__ == "__main__":
    top_level_cli(USBVendorDeviceExample)
