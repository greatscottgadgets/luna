#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from nmigen              import Elaboratable, Module, Cat

from luna                import top_level_cli
from luna.usb2           import USBDevice, USBStreamInEndpoint, USBStreamOutEndpoint

from luna.gateware.platform                      import NullPin
from luna.gateware.usb.usb2.request              import StallOnlyRequestHandler

from usb_protocol.types                import USBRequestType, USBDirection
from usb_protocol.emitters             import DeviceDescriptorCollection
from usb_protocol.types.descriptors    import uac
from usb_protocol.emitters.descriptors import uac

class USB2MidiExample(Elaboratable):
    """ Demonstrates the use of USB MIDI """
    MAX_PACKET_SIZE = 512

    def create_descriptors(self):
        """ Creates the descriptors that describe our MIDI topology. """

        descriptors = DeviceDescriptorCollection()

        # Create a device descriptor with our user parameters...
        with descriptors.DeviceDescriptor() as d:
            d.bcdUSB             = 2.00
            d.bDeviceClass       = 0xEF
            d.bDeviceSubclass    = 0x02
            d.bDeviceProtocol    = 0x01
            d.idVendor           = 0x16d0
            d.idProduct          = 0x0f3b

            d.iManufacturer      = "LUNA"
            d.iProduct           = "LUNA USB MIDI demo"
            d.iSerialNumber      = "0815"
            d.bcdDevice          = 0.01

            d.bNumConfigurations = 1

        with descriptors.ConfigurationDescriptor() as configDescr:
            interface = uac.StandardMidiStreamingInterfaceDescriptorEmitter()
            interface.bInterfaceNumber = 0
            interface.bNumEndpoints = 1 # 2
            configDescr.add_subordinate_descriptor(interface)

            streamingInterface = uac.ClassSpecificMidiStreamingInterfaceDescriptorEmitter()

            # prevent the descriptor from getting too large, see https://github.com/greatscottgadgets/luna/issues/86
            #outToHostJack = uac.MidiOutJackDescriptorEmitter()
            #outToHostJack.bJackID = 1
            #outToHostJack.bJackType = uac.MidiStreamingJackTypes.EMBEDDED
            #outToHostJack.add_source(2)
            #streamingInterface.add_subordinate_descriptor(outToHostJack)
#
            #inToDeviceJack = uac.MidiInJackDescriptorEmitter()
            #inToDeviceJack.bJackID = 2
            #inToDeviceJack.bJackType = uac.MidiStreamingJackTypes.EXTERNAL
            #streamingInterface.add_subordinate_descriptor(inToDeviceJack)

            inFromHostJack = uac.MidiInJackDescriptorEmitter()
            inFromHostJack.bJackID = 3
            inFromHostJack.bJackType = uac.MidiStreamingJackTypes.EMBEDDED
            streamingInterface.add_subordinate_descriptor(inFromHostJack)

            outFromDeviceJack = uac.MidiOutJackDescriptorEmitter()
            outFromDeviceJack.bJackID = 4
            outFromDeviceJack.bJackType = uac.MidiStreamingJackTypes.EXTERNAL
            outFromDeviceJack.add_source(3)
            streamingInterface.add_subordinate_descriptor(outFromDeviceJack)

            outEndpoint = uac.StandardMidiStreamingBulkDataEndpointDescriptorEmitter()
            outEndpoint.bEndpointAddress = USBDirection.OUT.to_endpoint_address(1)
            outEndpoint.wMaxPacketSize = self.MAX_PACKET_SIZE
            streamingInterface.add_subordinate_descriptor(outEndpoint)

            outMidiEndpoint = uac.ClassSpecificMidiStreamingBulkDataEndpointDescriptorEmitter()
            outMidiEndpoint.add_associated_jack(3)
            streamingInterface.add_subordinate_descriptor(outMidiEndpoint)

            # prevent the descriptor from getting too large, see https://github.com/greatscottgadgets/luna/issues/86
            #inEndpoint = uac.StandardMidiStreamingDataEndpointDescriptorEmitter()
            #inEndpoint.bEndpointAddress = USBDirection.IN.from_endpoint_address(1)
            #inEndpoint.wMaxPacketSize = self.MAX_PACKET_SIZE
            #streamingInterface.add_subordinate_descriptor(inEndpoint)
#
            #inMidiEndpoint = uac.ClassSpecificMidiStreamingBulkDataEndpointDescriptorEmitter()
            #inMidiEndpoint.add_associated_jack(1)
            #streamingInterface.add_subordinate_descriptor(inMidiEndpoint)

            configDescr.add_subordinate_descriptor(streamingInterface)

        return descriptors

    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our USB-to-serial converter.
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        control_ep = usb.add_standard_control_endpoint(descriptors)

        # Attach class-request handlers that stall any vendor or reserved requests,
        # as we don't have or need any.
        stall_condition = lambda setup : \
            (setup.type == USBRequestType.VENDOR) | \
            (setup.type == USBRequestType.RESERVED)
        control_ep.add_request_handler(StallOnlyRequestHandler(stall_condition))

        ep1_out = USBStreamOutEndpoint(
            endpoint_number=1, # EP 1 OUT
            max_packet_size=self.MAX_PACKET_SIZE
        )
        usb.add_endpoint(ep1_out)

        #ep1_in = USBStreamInEndpoint(
        #    endpoint_number=1, # EP 1 IN
        #    max_packet_size=self.MAX_PACKET_SIZE
        #)
        #usb.add_endpoint(ep1_in)

        leds    = Cat(platform.request_optional("led", i, default=NullPin()) for i in range(8))
        with m.If(ep1_out.stream.valid):
            m.d.usb += [
                leds     .eq(ep1_out.stream.payload),
            ]

        # Always accept data as it comes in.
        m.d.comb += ep1_out.stream.ready.eq(1)

        # Connect our device as a high speed device
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(0),
        ]

        return m

if __name__ == "__main__":
    e = USB2MidiExample()
    d = e.create_descriptors()
    descriptor_bytes = d.get_descriptor_bytes(2)
    print(f"descriptor length: {len(descriptor_bytes)} bytes: {str(descriptor_bytes.hex())}")
    top_level_cli(USB2MidiExample)