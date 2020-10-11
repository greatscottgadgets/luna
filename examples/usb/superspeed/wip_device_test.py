#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Incomplete example for working the SerDes-based a PIPE PHY. """

from nmigen import *
from nmigen.hdl.ast import Fell

from usb_protocol.emitters         import DeviceDescriptorCollection

from luna                          import top_level_cli
from luna.gateware.platform        import NullPin
from luna.gateware.usb.devices.ila import USBIntegratedLogicAnalyer, USBIntegratedLogicAnalyzerFrontend

from luna.usb3                     import USBSuperSpeedDevice

WITH_ILA = True

class USBSuperSpeedExample(Elaboratable):
    """ Work-in-progress example/test fixture for a SuperSpeed device. """


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

            # We're complying with the USB 3.2 standard.
            d.bcdUSB             = 3.2

            # USB3 requires this to be "9", to indicate 2 ** 9, or 512B.
            d.bMaxPacketSize0    = 9

            d.iManufacturer      = "LUNA"
            d.iProduct           = "SuperSpeed Test Device"
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


    def __init__(self):
        if WITH_ILA:
            self.endpoint_data        = Signal(32)
            self.source_data          = Signal(32)

            self.ila = USBIntegratedLogicAnalyer(
                bus="usb",
                domain="ss",
                signals=[
                    self.source_data,
                    self.endpoint_data
                ],
                sample_depth=256,
                max_packet_size=64,
                samples_pretrigger=6
            )

    def emit(self):
        frontend = USBIntegratedLogicAnalyzerFrontend(ila=self.ila)
        frontend.emit_vcd("/tmp/output.vcd")

    def elaborate(self, platform):
        m = Module()
        if WITH_ILA:
            m.submodules.ila = self.ila

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our core PIPE PHY. Since PHY configuration is per-board, we'll just ask
        # our platform for a pre-configured USB3 PHY.
        m.submodules.phy = phy = platform.create_usb3_phy()

        # Create our core SuperSpeed device.
        m.submodules.usb = usb = USBSuperSpeedDevice(phy=phy, sync_frequency=50e6)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)


        # Heartbeat LED.
        counter = Signal(28)
        m.d.ss += counter.eq(counter + 1)

        m.d.comb += [
            platform.get_led(m, 0).o.eq(usb.link_trained),

            # Heartbeat.
            platform.get_led(m, 7).o.eq(counter[-1]),
        ]


        if WITH_ILA:
            m.d.comb += [
                # ILA
                self.source_data     .eq(usb.tx_data_tap.data),
                self.endpoint_data   .eq(usb.ep_tx_stream.data),
                self.ila.trigger     .eq(usb.ep_tx_stream.first),
            ]

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    ex = top_level_cli(USBSuperSpeedExample)
    if WITH_ILA:
        ex.emit()
