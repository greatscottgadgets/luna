#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import sys
import logging
import os.path

from amaranth                                import Elaboratable, Module, Cat
from amaranth.hdl.rec                        import Record

from lambdasoc.periph                        import Peripheral
from lambdasoc.periph.serial                 import AsyncSerialPeripheral
from lambdasoc.periph.timer                  import TimerPeripheral

from luna                                    import top_level_cli
from luna.gateware.soc                       import SimpleSoC

from luna.gateware.usb.usb2.device           import USBDevice, USBDeviceController
from luna.gateware.usb.usb2.interfaces.eptri import SetupFIFOInterface, InFIFOInterface, OutFIFOInterface


CLOCK_FREQUENCIES_MHZ = {
    'sync': 60
}


class LEDPeripheral(Peripheral, Elaboratable):
    """ Example peripheral that controls the board's LEDs. """

    def __init__(self):
        super().__init__()

        # Create our LED register.
        # Note that there's a bunch of 'magic' that goes on behind the scenes, here:
        # a memory address will automatically be reserved for this register in the address
        # space it's attached to; and the SoC utilities will automatically generate header
        # entires and stub functions for it.
        bank            = self.csr_bank()
        self._output    = bank.csr(6, "w")

        # ... and convert our register into a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus


    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        # Grab our LEDS...
        leds = Cat(platform.request("led", i) for i in range(6))

        # ... and update them on each register write.
        with m.If(self._output.w_stb):
            m.d.sync += leds.eq(self._output.w_data)

        return m



class TinyUSBSoC(Elaboratable):
    """ Simple SoC for hosting TinyUSB. """

    RAM_SIZE          = 0x0001_0000

    RAM_ADDRESS       = 0x0004_0000
    USB_CORE_ADDRESS  = 0x0005_0000
    USB_SETUP_ADDRESS = 0x0006_0000
    USB_IN_ADDRESS    = 0x0007_0000
    USB_OUT_ADDRESS   = 0x0008_0000
    LEDS_ADDRESS      = 0x0009_0000

    def __init__(self):

        # Create a stand-in for our UART.
        self.uart_pins = Record([
            ('rx', [('i', 1)]),
            ('tx', [('o', 1)])
        ])

        # Create our SoC...
        self.soc = soc = SimpleSoC()
        soc.add_bios_and_peripherals(uart_pins=self.uart_pins, fixed_addresses=True)

        # ... add some bulk RAM ...
        soc.add_ram(self.RAM_SIZE, addr=self.RAM_ADDRESS)

        # ... a core USB controller ...
        self.usb_device_controller = USBDeviceController()
        soc.add_peripheral(self.usb_device_controller, addr=self.USB_CORE_ADDRESS)

        # ... our eptri peripherals.
        self.usb_setup = SetupFIFOInterface()
        soc.add_peripheral(self.usb_setup, as_submodule=False, addr=self.USB_SETUP_ADDRESS)

        self.usb_in_ep = InFIFOInterface()
        soc.add_peripheral(self.usb_in_ep, as_submodule=False, addr=self.USB_IN_ADDRESS)

        self.usb_out_ep = OutFIFOInterface()
        soc.add_peripheral(self.usb_out_ep, as_submodule=False, addr=self.USB_OUT_ADDRESS)

        # ... and our LED peripheral, for simple output.
        leds = LEDPeripheral()
        soc.add_peripheral(leds, addr=self.LEDS_ADDRESS)


    def elaborate(self, platform):
        m = Module()
        m.submodules.soc = self.soc

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator(clock_frequencies=CLOCK_FREQUENCIES_MHZ)

        # Connect up our UART.
        uart_io = platform.request("uart", 0)
        m.d.comb += [
            uart_io.tx         .eq(self.uart_pins.tx),
            self.uart_pins.rx  .eq(uart_io.rx)
        ]

        if hasattr(uart_io.tx, 'oe'):
            m.d.comb += uart_io.tx.oe.eq(~self.soc.uart._phy.tx.rdy),

        # Create our USB device.
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # Connect up our device controller.
        m.d.comb += self.usb_device_controller.attach(usb)

        # Add our eptri endpoint handlers.
        usb.add_endpoint(self.usb_setup)
        usb.add_endpoint(self.usb_in_ep)
        usb.add_endpoint(self.usb_out_ep)
        return m


if __name__ == "__main__":
    design = TinyUSBSoC()
    top_level_cli(design, cli_soc=design.soc)
