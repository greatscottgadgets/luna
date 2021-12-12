#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import operator
from functools import reduce

from amaranth import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from amaranth.lib.cdc import FFSynchronizer

from luna.gateware.utils.cdc       import synchronize
from luna.gateware.interface.spi   import SPIRegisterInterface
from luna.gateware.interface.flash import ECP5ConfigurationFlashInterface

REGISTER_ID             = 1

class DebugControllerFlashBridge(Elaboratable):
    """ Hardware that makes the configuration flash accessible from the Debug Controller. """

    def elaborate(self, platform):
        m = Module()

        # Create a set of registers, and expose them over SPI.
        board_spi = platform.request("debug_spi")
        spi_registers = SPIRegisterInterface(default_read_value=-1)
        m.submodules.spi_registers = spi_registers

        # Identify ourselves as the SPI flash bridge.
        spi_registers.add_read_only_register(REGISTER_ID, read=0x53504946)


        #
        # SPI flash passthrough connections.
        #
        flash_sdo = Signal()

        spi_flash_bus = platform.request('spi_flash')
        spi_flash_passthrough = ECP5ConfigurationFlashInterface(bus=spi_flash_bus)

        m.submodules += spi_flash_passthrough
        m.d.comb += [
            spi_flash_passthrough.sck   .eq(board_spi.sck),
            spi_flash_passthrough.sdi   .eq(board_spi.sdi),
            flash_sdo                   .eq(spi_flash_passthrough.sdo),
        ]

        #
        # Structural connections.
        #
        spi = synchronize(m, board_spi)

        # Select the passthrough or gateware SPI based on our chip-select values.
        gateware_sdo = Signal()
        with m.If(board_spi.cs):
            m.d.comb += board_spi.sdo.eq(gateware_sdo)
        with m.Else():
            m.d.comb += board_spi.sdo.eq(flash_sdo)

        # Connect our register interface to our board SPI.
        m.d.comb += [
            spi_registers.spi.sck .eq(spi.sck),
            spi_registers.spi.sdi .eq(spi.sdi),
            gateware_sdo          .eq(spi_registers.spi.sdo),
            spi_registers.spi.cs  .eq(spi.cs)
        ]

        return m

