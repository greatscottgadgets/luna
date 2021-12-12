#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth            import Elaboratable, Module

from luna                import top_level_cli
from luna.full_devices   import USBSerialDevice


class USBSerialDeviceExample(Elaboratable):
    """ Device that acts as a 'USB-to-serial' loopback using our premade gateware. """

    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our USB-to-serial converter.
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.usb_serial = usb_serial = \
                USBSerialDevice(bus=ulpi, idVendor=0x16d0, idProduct=0x0f3b)

        m.d.comb += [
            # Place the streams into a loopback configuration...
            usb_serial.tx.payload  .eq(usb_serial.rx.payload),
            usb_serial.tx.valid    .eq(usb_serial.rx.valid),
            usb_serial.tx.first    .eq(usb_serial.rx.first),
            usb_serial.tx.last     .eq(usb_serial.rx.last),
            usb_serial.rx.ready    .eq(usb_serial.tx.ready),

            # ... and always connect by default.
            usb_serial.connect     .eq(1)
        ]

        return m

if __name__ == "__main__":
    top_level_cli(USBSerialDeviceExample)
