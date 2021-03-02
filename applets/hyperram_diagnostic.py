#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import time

from prompt_toolkit import HTML
from prompt_toolkit import print_formatted_text as pprint

from nmigen import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from nmigen.lib.cdc import FFSynchronizer

from luna                             import top_level_cli
from apollo_fpga                           import ApolloDebugger, ApolloILAFrontend
from luna.gateware.utils.cdc          import synchronize
from luna.gateware.interface.spi      import SPIRegisterInterface, SPIMultiplexer, SPIBus
from luna.gateware.architecture.car   import LunaECP5DomainGenerator
from luna.gateware.interface.psram    import HyperRAMInterface

REGISTER_RAM_REG_ADDR   = 2
REGISTER_RAM_VALUE      = 3


class HyperRAMDiagnostic(Elaboratable):
    """
    Temporary gateware that evaluates HyperRAM skews.
    """


    def elaborate(self, platform):
        m = Module()

        # Generate our clock domains.
        clocking = LunaECP5DomainGenerator()
        m.submodules.clocking = clocking

        # Grab a reference to our debug-SPI bus.
        board_spi = synchronize(m, platform.request("debug_spi"))

        # Create a set of registers...
        spi_registers = SPIRegisterInterface(7, 32)
        m.submodules.spi_registers = spi_registers
        m.d.comb += spi_registers.spi.connect(board_spi)


        #
        # HyperRAM test connections.
        #
        ram_bus = platform.request('ram')
        psram = HyperRAMInterface(bus=ram_bus, **platform.ram_timings)
        m.submodules += psram

        psram_address_changed = Signal()
        psram_address = spi_registers.add_register(REGISTER_RAM_REG_ADDR, write_strobe=psram_address_changed)

        spi_registers.add_sfr(REGISTER_RAM_VALUE, read=psram.read_data)

        # Hook up our PSRAM.
        m.d.comb += [
            ram_bus.reset          .eq(0),
            psram.single_page      .eq(0),
            psram.perform_write    .eq(0),
            psram.register_space   .eq(1),
            psram.final_word       .eq(1),
            psram.start_transfer   .eq(psram_address_changed),
            psram.address          .eq(psram_address),
        ]

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    test = top_level_cli(HyperRAMDiagnostic)

    # Create a debug and ILA connection.
    debugger = ApolloDebugger()

    print("Running basic HyperRAM diagnostics.")

    iterations = 100

    passes   = 0
    failures = 0
    failed_tests = set()

    def test_id_read():
        debugger.spi.register_write(REGISTER_RAM_REG_ADDR, 0x0)
        debugger.spi.register_write(REGISTER_RAM_REG_ADDR, 0x0)
        return debugger.spi.register_read(REGISTER_RAM_VALUE) == 0x0c81

    def test_config_read():
        debugger.spi.register_write(REGISTER_RAM_REG_ADDR, 0x800)
        debugger.spi.register_write(REGISTER_RAM_REG_ADDR, 0x800)
        return debugger.spi.register_read(REGISTER_RAM_VALUE) == 0x8f1f

    # Run each of our tests.
    for test in (test_id_read, test_config_read):
        for i in range(iterations):

            if test():
                pprint(f".", end="")
                passes += 1
            else:
                pprint(f"✗", end="")

                failures += 1
                failed_tests.add(test)

    fail_text = "<red>✗ FAILED</red>"
    pass_text = "<green>✓ PASSED</green>"
    pprint(HTML("\n\n<b><u>Results:</u></b>"))

    pprint(HTML(f"    ID READ:     {fail_text if test_id_read in failed_tests else pass_text}"))
    pprint(HTML(f"    CONFIG READ: {fail_text if test_config_read in failed_tests else pass_text}"))


    print(f"\nDiagnostics completed with {passes} passes and {failures} failures.\n")
