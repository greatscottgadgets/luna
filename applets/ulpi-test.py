#!/usr/bin/env python3
#
# This file is part of LUNA.
#

import sys
import time

from prompt_toolkit import HTML
from prompt_toolkit import print_formatted_text as pprint

from nmigen import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from nmigen.lib.cdc import FFSynchronizer

from luna                             import top_level_cli

from luna.apollo                      import ApolloDebugger, ApolloILAFrontend
from luna.gateware.debug.ila          import SyncSerialILA


from luna.gateware.utils.cdc          import synchronize
from luna.gateware.utils              import rising_edge_detector
from luna.gateware.architecture.car   import LunaECP5DomainGenerator
from luna.gateware.interface.spi      import SPIRegisterInterface, SPIMultiplexer, SPIBus

from luna.gateware.interface.ulpi     import UMTITranslator

REGISTER_ILA = 2


class ULPIDiagnostic(Elaboratable):
    """ Gateware that evalutes ULPI PHY functionality. """


    def elaborate(self, platform):
        m = Module()

        # Generate our clock domains.
        clocking = LunaECP5DomainGenerator()
        m.submodules.clocking = clocking

        # Grab a reference to our debug-SPI bus.
        board_spi = synchronize(m, platform.request("debug_spi"))

        # Create our SPI-connected registers.
        m.submodules.spi_registers = spi_registers = SPIRegisterInterface(7, 32)
        m.d.comb += spi_registers.spi.connect(board_spi)

        # Create our UMTI translator.
        ulpi = platform.request("sideband_phy")
        m.submodules.umti = umti = UMTITranslator(ulpi=ulpi)


        # Strap our power controls to be in VBUS passthrough by default,
        # on the target port.
        m.d.comb += [
            platform.request("power_a_port")      .eq(0),
            platform.request("pass_through_vbus") .eq(1),
        ]


        # Hook up our LEDs to status signals.
        m.d.comb += [
            platform.request("led", 0)  .eq(umti.vbus_valid),
            platform.request("led", 1)  .eq(umti.session_valid),
            platform.request("led", 2)  .eq(umti.session_end),
            platform.request("led", 3)  .eq(umti.rx_active),
            platform.request("led", 4)  .eq(umti.rx_error)
        ]

        spi_registers.add_read_only_register(1, read=umti.last_rx_command)


        # For debugging: mirror some ULPI signals on the UIO.
        user_io = Cat(platform.request("user_io", i, dir="o") for i in range(0, 4))
        m.d.comb += [
            user_io[0]  .eq(ClockSignal("ulpi")),
            user_io[1]  .eq(ulpi.dir),
            user_io[2]  .eq(ulpi.nxt),
            user_io[3]  .eq(ulpi.stp),
        ]


        # Return our elaborated module.
        return m


if __name__ == "__main__":
    top_level_cli(ULPIDiagnostic)
