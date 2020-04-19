#!/usr/bin/env python3
#
# This file is part of LUNA.
#

from nmigen                       import Elaboratable, Module

from luna                         import top_level_cli
from luna.gateware.soc            import SimpleSoC
from luna.gateware.interface.uart import UARTTransmitterPeripheral


class LunaCPUExample(Elaboratable):
    """ Simple example of building a simple SoC around LUNA. """


    def elaborate(self, platform):
        m = Module()
        clock_freq = 60e6

        # Grab a reference to our UART.
        uart_io = platform.request("uart", 0)

        # Create our SoC...
        m.submodules.soc = soc = SimpleSoC()
        soc.add_firmware_rom('hello_world.bin')
        soc.add_ram(0x1000, addr=0x10000000)

        # ... and add our UART peripheral.
        uart = UARTTransmitterPeripheral(divisor=int(clock_freq // 115200))
        soc.add_peripheral(uart, addr=0x80000000, sparse=True)

        # Connect the transmitter to the debug transmitter output.
        m.d.comb += uart_io.tx.o.eq(uart.tx)

        return m


if __name__ == "__main__":
    top_level_cli(LunaCPUExample)
