#!/usr/bin/env python3
#
# This file is part of LUNA.
#

from nmigen                                  import Elaboratable, Module, Cat
from nmigen.hdl.rec                          import Record

from lambdasoc.periph.serial                 import AsyncSerialPeripheral
from lambdasoc.periph.timer                  import TimerPeripheral

from luna                                    import top_level_cli
from luna.gateware.soc                       import SimpleSoC

from luna.gateware.usb.usb2.device           import USBDevice, USBDeviceController
from luna.gateware.usb.usb2.interfaces.eptri import SetupFIFOInterface, InFIFOInterface, OutFIFOInterface




CLOCK_FREQUENCIES_MHZ = {
    'sync': 60
}


class EptriDeviceExample(Elaboratable):
    """ Example of an Eptri-equivalent USB device built with LUNA. """

    def __init__(self):

        # Create a stand-in for our UART.
        self.uart_pins = Record([
            ('rx', [('i', 1)]),
            ('tx', [('o', 1)])
        ])

        # Create our SoC...
        self.soc = soc = SimpleSoC()

        # ... add our firmware image ...
        soc.add_rom("eptri_example.bin", 0x4000)

        # ... add some bulk RAM ...
        soc.add_ram(0x4000)

        # ... add a UART ...
        self.uart = uart = AsyncSerialPeripheral(divisor=int(60e6 // 115200), pins=self.uart_pins)
        soc.add_peripheral(uart)

        # ... add a timer, to control our LED blinkies...
        self.timer = timer = TimerPeripheral(24)
        soc.add_peripheral(timer)


        # ... a core USB controller ...
        self.controller = USBDeviceController()
        soc.add_peripheral(self.controller)

        # ... and add our eptri peripherals.
        self.setup = SetupFIFOInterface()
        soc.add_peripheral(self.setup, as_submodule=False)

        self.in_ep = InFIFOInterface()
        soc.add_peripheral(self.in_ep, as_submodule=False)

        self.out_ep = OutFIFOInterface()
        soc.add_peripheral(self.out_ep, as_submodule=False)



    def elaborate(self, platform):
        m = Module()
        m.submodules.soc = self.soc

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator(CLOCK_FREQUENCIES_MHZ)

        # Connect up our UART.
        uart_io = platform.request("uart", 0)
        m.d.comb += [
            uart_io.tx         .eq(self.uart_pins.tx),
            self.uart_pins.rx  .eq(uart_io.rx)
        ]

        # Create our USB device.
        ulpi = platform.request("target_phy")
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # Connect up our device controller.
        m.d.comb += self.controller.attach(usb)

        # Add our eptri endpoint handlers.
        usb.add_endpoint(self.setup)
        usb.add_endpoint(self.in_ep)
        usb.add_endpoint(self.out_ep)
        return m


if __name__ == "__main__":
    design = EptriDeviceExample()
    top_level_cli(design, cli_soc=design.soc)
