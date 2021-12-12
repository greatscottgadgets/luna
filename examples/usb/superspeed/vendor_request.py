#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth import *
from amaranth.hdl.ast import Fell

from usb_protocol.types            import USBRequestType
from usb_protocol.emitters         import SuperSpeedDeviceDescriptorCollection

from luna                          import top_level_cli
from luna.gateware.platform        import NullPin

from luna.usb3                     import USBSuperSpeedDevice, SuperSpeedRequestHandler


class LEDRequestHandler(SuperSpeedRequestHandler):
    """ Simple, example request handler that can control the board's LEDs. """

    REQUEST_SET_LEDS = 0

    def elaborate(self, platform):
        m = Module()

        interface         = self.interface
        setup             = self.interface.setup

        # Grab a reference to the board's LEDs.
        leds  = Cat(platform.request_optional("led", i, default=NullPin()).o for i in range(32))

        #
        # Vendor request handlers.

        with m.If(setup.type == USBRequestType.VENDOR):

            with m.Switch(setup.request):

                # SET_LEDS request handler: handler that sets the board's LEDS
                # to a user provided value
                with m.Case(self.REQUEST_SET_LEDS):

                    # If we have an active data byte, splat it onto the LEDs.
                    #
                    # For simplicity of this example, we'll accept any word in
                    # the packet; and not just the first one; each word will
                    # cause an update. This is fun; we can PWM the LEDs with
                    # USB packets. :)
                    for word in range(4):
                        with m.If(interface.rx.valid[word]):
                            led_byte = leds.word_select(word, 8)
                            m.d.ss += led_byte.eq(interface.rx.payload.word_select(word, 8))

                    # Generate an ACK response once we receive the packet.
                    #
                    # Note that we generate an ACK no matter whether the packet was received correctly
                    # or not. If it was received incorrectly, we'll set the ``retry`` bit.
                    with m.If(interface.rx_complete | interface.rx_invalid):
                        m.d.comb += [
                            interface.handshakes_out.retry_required   .eq(interface.rx_invalid),
                            interface.handshakes_out.next_sequence    .eq(1),
                            interface.handshakes_out.send_ack         .eq(1)
                        ]

                    # Once the receive is complete, respond with an ACK.
                    with m.If(interface.status_requested):
                        m.d.comb += [
                            interface.handshakes_out.next_sequence    .eq(1),
                            interface.handshakes_out.send_ack         .eq(1)
                        ]


                with m.Default():

                    #
                    # Stall unhandled requests.
                    #
                    have_opportunity_to_stall = (
                        interface.rx_complete        |
                        interface.rx_invalid         |
                        interface.status_requested   |
                        interface.data_requested
                    )

                    with m.If(have_opportunity_to_stall):
                        m.d.comb += interface.handshakes_out.send_stall.eq(1)

                return m


class SuperSpeedVendorDeviceExample(Elaboratable):
    """ Simple example of a USB SuperSpeed device using the LUNA framework. """


    def create_descriptors(self):
        """ Create the descriptors we want to use for our device. """

        descriptors = SuperSpeedDeviceDescriptorCollection()

        #
        # We'll add the major components of the descriptors we we want.
        # The collection we build here will be necessary to create a standard endpoint.
        #

        # We'll need a device descriptor...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = 0x16d0
            d.idProduct          = 0xf3b

            # We're complying with the USB 3.2 standard.
            d.bcdUSB             = 3.2

            # USB3 requires this to be "9", to indicate 2 ** 9, or 512B.
            d.bMaxPacketSize0    = 9

            d.iManufacturer      = "LUNA"
            d.iProduct           = "Vendor Test Device"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:
            c.bMaxPower        = 50

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

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
        control_ep = usb.add_standard_control_endpoint(descriptors)

        # Add our vendor request handler to our control endpoint.
        control_ep.add_request_handler(LEDRequestHandler())

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    top_level_cli(SuperSpeedVendorDeviceExample)
