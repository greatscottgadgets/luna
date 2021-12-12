#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import time
import logging

from prompt_toolkit import HTML
from prompt_toolkit import print_formatted_text as pprint

from amaranth import Signal, Elaboratable, Module

from luna                             import top_level_cli
from apollo_fpga                      import ApolloDebugger
from luna.gateware.interface.jtag     import JTAGRegisterInterface
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

        # Create a set of registers...
        registers = JTAGRegisterInterface(address_size=7, default_read_value=0xDEADBEEF)
        m.submodules.registers = registers

        #
        # HyperRAM test connections.
        #
        ram_bus = platform.request('ram')
        psram = HyperRAMInterface(bus=ram_bus, **platform.ram_timings)
        m.submodules += psram

        psram_address_changed = Signal()
        psram_address = registers.add_register(REGISTER_RAM_REG_ADDR, write_strobe=psram_address_changed)

        registers.add_sfr(REGISTER_RAM_VALUE, read=psram.read_data)

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
    dut = ApolloDebugger()
    logging.info(f"Connected to onboard dut; hardware revision r{dut.major}.{dut.minor} (s/n: {dut.serial_number}).")

    logging.info("Running basic HyperRAM diagnostics.")

    iterations = 100

    passes   = 0
    failures = 0
    failed_tests = set()

    def test_id_read():
        dut.registers.register_write(REGISTER_RAM_REG_ADDR, 0x0)
        dut.registers.register_write(REGISTER_RAM_REG_ADDR, 0x0)
        return dut.registers.register_read(REGISTER_RAM_VALUE) in (0x0c81, 0x0c86)

    def test_config_read():
        dut.registers.register_write(REGISTER_RAM_REG_ADDR, 0x800)
        dut.registers.register_write(REGISTER_RAM_REG_ADDR, 0x800)
        return dut.registers.register_read(REGISTER_RAM_VALUE) in (0x8f1f, 0x8f2f)


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
