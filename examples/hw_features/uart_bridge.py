#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
"""
Example of using the debug controller's UART bridge.

Connect to the ttyACM connection at 115200 baud, 8N1,
and you should see "Hello World" 'typed' repeatedly.
"""

from amaranth import Signal, Elaboratable, Module, Array, Cat

from luna import top_level_cli
from luna.gateware.interface.uart import UARTTransmitter


class UARTBridgeExample(Elaboratable):

    def elaborate(self, platform):
        m = Module()
        uart = platform.request("uart")

        clock_freq = int(60e6)
        char_freq  = int(6e6)

        # Create our UART transmitter.
        transmitter = UARTTransmitter(divisor=int(clock_freq // 115200))
        m.submodules.transmitter = transmitter
        stream = transmitter.stream

        # Create a counter that will let us transmit ten times per second.
        counter = Signal(range(0, char_freq))
        with m.If(counter == (char_freq - 1)):
            m.d.sync += counter.eq(0)
        with m.Else():
            m.d.sync += counter.eq(counter + 1)

        # Create a simple ROM with a message for ourselves...
        letters = Array(ord(i) for i in "Hello, world! \r\n")

        # ... and count through it whenever we send a letter.
        current_letter = Signal(range(0, len(letters)))
        with m.If(stream.ready):
            m.d.sync += current_letter.eq(current_letter + 1)

        # Hook everything up.
        m.d.comb += [
            stream.payload  .eq(letters[current_letter]),
            stream.valid    .eq(counter == 0),

            uart.tx.o       .eq(transmitter.tx),
        ]

        # If this platform has an output-enable control on its UART, drive it iff
        # we're actively driving a transmission.
        if hasattr(uart.tx, 'oe'):
            m.d.comb += uart.tx.oe.eq(transmitter.driving),


        # Turn on a single LED, just to show something's running.
        led = Cat(platform.request('led', i) for i in range(6))
        m.d.comb += led.eq(~transmitter.tx)

        return m


if __name__ == "__main__":
    top_level_cli(UARTBridgeExample)
