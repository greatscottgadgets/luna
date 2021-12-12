#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth import Signal, Elaboratable, Module
from amaranth.lib.cdc import FFSynchronizer

from luna import top_level_cli
from luna.gateware.utils.cdc import synchronize
from luna.gateware.interface.spi import SPIDeviceInterface, SPIBus


class DebugSPIExample(Elaboratable):
    """ Hardware meant to demonstrate use of the Debug Controller's SPI interface. """


    def __init__(self):

        # Base ourselves around an SPI command interface.
        self.interface = SPIDeviceInterface(clock_phase=1)


    def elaborate(self, platform):
        m = Module()
        board_spi = platform.request("debug_spi")

        # Use our command interface.
        m.submodules.interface = self.interface

        #
        # Synchronize and connect our SPI.
        #
        spi = synchronize(m, board_spi)
        m.d.comb  += self.interface.spi.connect(spi)

        # Turn on a single LED, just to show something's running.
        led = platform.request('led', 0)
        m.d.comb += led.eq(1)

        # Echo back the last received data.
        m.d.comb += self.interface.word_out.eq(self.interface.word_in)

        return m


if __name__ == "__main__":
    top_level_cli(DebugSPIExample)
