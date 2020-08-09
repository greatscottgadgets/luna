#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from nmigen                          import Elaboratable, Module, Signal

from luna                            import top_level_cli
from luna.gateware.usb.devices.hid   import HIDDevice 

class USBHIDExample(Elaboratable):
    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create the 32-bit counter we'll be using as our status signal.
        counter = Signal(32)
        m.d.usb += counter.eq(counter + 1)

        # Create our USB device interface...
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.hid = hid = \
                HIDDevice(bus=ulpi, idVendor=0x1337, idProduct=0x1337)

        # Connect counter as a pollable report
        hid.add_input(counter)

        m.d.comb += [
            hid.connect.eq(1)
        ]

        return m

if __name__ == "__main__":
    top_level_cli(USBHIDExample)