#!/usr/bin/env python3
#
# This file is part of LUNA.
#

from nmigen import Signal, Elaboratable, Module, Cat
from nmigen.lib.cdc import FFSynchronizer

from luna.gateware.platform import *
from luna.gateware.interface.spi import SPIRegisterInterface


class DebugSPIRegisterExample(Elaboratable):
    """ Hardware meant to demonstrate use of the Debug Controller's register interface. """


    def elaborate(self, platform):
        m = Module()
        board_spi = platform.request("debug_spi")

        # Create a set of registers, and expose them over SPI.
        spi_registers = SPIRegisterInterface(default_read_value=0x4C554E41A) #default read = u'LUNA'
        m.submodules.spi_registers = spi_registers

        # Fill in some example registers.
        # (Register 0 is reserved for size autonegotiation).
        spi_registers.add_read_only_register(1, read=0xc001cafe)
        led_reg = spi_registers.add_register(2, size=6, name="leds")
        spi_registers.add_read_only_register(3, read=0xdeadbeef)

        # ... and tie our LED register to our LEDs.
        led_out   = Cat([platform.request("led", i, dir="o") for i in range(0, 6)])
        m.d.comb += led_out.eq(led_reg)

        #
        # Structural connections.
        #
        sck = Signal()
        sdi = Signal()
        sdo = Signal()
        cs  = Signal()

        #
        # Synchronize each of our I/O SPI signals, where necessary.
        #
        m.submodules += FFSynchronizer(board_spi.sck, sck)
        m.submodules += FFSynchronizer(board_spi.sdi, sdi)
        m.submodules += FFSynchronizer(board_spi.cs,  cs)
        m.d.comb     += board_spi.sdo.eq(sdo)

        # Connect our register interface to our board SPI.
        m.d.comb += [
            spi_registers.sck.eq(sck),
            spi_registers.sdi.eq(sdi),
            sdo.eq(spi_registers.sdo),
            spi_registers.cs .eq(cs)
        ]

        return m


if __name__ == "__main__":
    platform = LUNAPlatformR01()
    platform.build(DebugSPIRegisterExample(), do_program=True)
