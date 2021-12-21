#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth import Signal, Elaboratable, Module, Cat
from amaranth.lib.cdc import FFSynchronizer

from luna import top_level_cli

from luna.gateware.utils.cdc     import synchronize
from luna.gateware.interface.spi import SPIRegisterInterface
from luna.gateware.platform      import NullPin

class DebugSPIRegisterExample(Elaboratable):
    """ Gateware meant to demonstrate use of the Debug Controller's register interface. """


    def elaborate(self, platform):
        m = Module()
        board_spi = platform.request("debug_spi")

        # Create a set of registers, and expose them over SPI.
        spi_registers = SPIRegisterInterface(default_read_value=0x4C554E41) #default read = u'LUNA'
        m.submodules.spi_registers = spi_registers

        # Fill in some example registers.
        # (Register 0 is reserved for size autonegotiation).
        spi_registers.add_read_only_register(1, read=0xc001cafe)
        led_reg = spi_registers.add_register(2, size=6, name="leds")
        spi_registers.add_read_only_register(3, read=0xdeadbeef)

        # ... and tie our LED register to our LEDs.
        led_out   = Cat([platform.request_optional("led", i, default=NullPin()).o for i in range(0, 8)])
        m.d.comb += led_out.eq(led_reg)

        # Connect up our synchronized copies of the SPI registers.
        spi = synchronize(m, board_spi)
        m.d.comb += spi_registers.spi.connect(spi)


        return m


if __name__ == "__main__":
    top_level_cli(DebugSPIRegisterExample)
