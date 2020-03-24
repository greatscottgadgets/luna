#!/usr/bin/env python3
#
# This file is part of LUNA.
#

from nmigen                         import Elaboratable, Module, Cat, Signal

from luna                           import top_level_cli
from luna.gateware.architecture.car import LunaECP5DomainGenerator
from luna.gateware.usb.usb2.device  import USBDevice


class USBDeviceExample(Elaboratable):
    """ Simple example of a USB device using the LUNA framework. """


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = LunaECP5DomainGenerator()

        # Create our USB device interface...
        ulpi = platform.request("target_phy")
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # Connect our device by default.
        m.d.comb += usb.connect.eq(1)

        # ... and for now, attach our LEDs to our most recent control request.
        leds = Cat(platform.request("led", i) for i in range(6))
        m.d.comb += leds.eq(usb.last_request)

        return m


if __name__ == "__main__":
    top_level_cli(USBDeviceExample)
