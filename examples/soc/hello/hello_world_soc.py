#!/usr/bin/env python3
#
# This file is part of LUNA.
#

from nmigen                       import Elaboratable, Module
from nmigen.hdl.rec               import Record

from lambdasoc.periph.serial      import AsyncSerialPeripheral

from luna                         import top_level_cli
from luna.gateware.soc            import SimpleSoC
from luna.gateware.interface.uart import UARTTransmitterPeripheral


class LunaCPUExample(Elaboratable):
    """ Simple example of building a simple SoC around LUNA. """

    def __init__(self):
        clock_freq = 60e6

        # Create our SoC...
        self.soc = soc = SimpleSoC()
        soc.add_rom('hello_world.bin', size=0x1000)
        soc.add_ram(0x1000)

        # ... and add our UART peripheral.
        self.uart_pins = Record([
            ('rx', [('i', 1)]),
            ('tx', [('o', 1)])
        ])
        self.uart = uart = AsyncSerialPeripheral(divisor=int(clock_freq // 115200), pins=self.uart_pins)
        soc.add_peripheral(uart)


    def elaborate(self, platform):
        m = Module()
        m.submodules.soc = self.soc

        # Connect up our UART.
        uart_io = platform.request("uart", 0)
        m.d.comb += [
            uart_io.tx         .eq(self.uart_pins.tx),
            self.uart_pins.rx  .eq(uart_io.rx)
        ]

        return m

1
if __name__ == "__main__":
    design = LunaCPUExample()
    top_level_cli(design, cli_soc=design.soc)
