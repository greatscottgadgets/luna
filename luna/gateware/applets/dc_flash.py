#
# This file is part of LUNA.
#

import operator
from functools import reduce

from nmigen import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from nmigen.lib.cdc import FFSynchronizer

from luna.gateware.platform        import get_appropriate_platform
from luna.gateware.interface.spi   import SPIRegisterInterface
from luna.gateware.interface.ulpi  import UMTITranslator
from luna.gateware.interface.flash import ECP5ConfigurationFlashInterface

REGISTER_ID             = 1

class DebugControllerFlashBridge(Elaboratable):
    """ Hardware that makes the configuration flash accessible from the Debug Controller. """

    def elaborate(self, platform):
        m = Module()

        clk_60MHz = platform.request(platform.default_clk)

        # Drive the sync clock domain with our main clock.
        m.domains.sync = ClockDomain()
        m.d.comb += ClockSignal().eq(clk_60MHz)

        # Create a set of registers, and expose them over SPI.
        board_spi = platform.request("debug_spi")
        spi_registers = SPIRegisterInterface(default_read_value=-1)
        m.submodules.spi_registers = spi_registers

        # Identify ourselves as the SPI flash bridge.
        spi_registers.add_read_only_register(REGISTER_ID, read=0x53504946)

        #
        # For now, keep resources on our right-side I/O network used.
        #
        platform.request("target_phy")

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
        sck = Signal()
        sdi = Signal()
        cs  = Signal()
        gateware_sdo = Signal()

        #
        # Synchronize each of our I/O SPI signals, where necessary.
        #
        m.submodules += FFSynchronizer(board_spi.sck, sck)
        m.submodules += FFSynchronizer(board_spi.sdi, sdi)
        m.submodules += FFSynchronizer(board_spi.cs,  cs)

        # Select the passthrough or gateware SPI based on our chip-select values.
        with m.If(spi_registers.cs):
            m.d.comb += board_spi.sdo.eq(gateware_sdo)
        with m.Else():
            m.d.comb += board_spi.sdo.eq(flash_sdo)

        # Connect our register interface to our board SPI.
        m.d.comb += [
            spi_registers.sck .eq(sck),
            spi_registers.sdi .eq(sdi),
            gateware_sdo      .eq(spi_registers.sdo),
            spi_registers.cs  .eq(cs)
        ]

        return m

