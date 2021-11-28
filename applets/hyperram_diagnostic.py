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
from amaranth.lib.fifo import SyncFIFO

from luna                             import top_level_cli
from apollo_fpga                      import ApolloDebugger
from luna.gateware.interface.jtag     import JTAGRegisterInterface
from luna.gateware.architecture.car   import LunaECP5DomainGenerator
from luna.gateware.interface.psram    import HyperRAMPHY, HyperRAMInterface

REGISTER_RAM_ADDR           = 2
REGISTER_RAM_FIFO           = 3
REGISTER_RAM_REGISTER_SPACE = 4
REGISTER_RAM_START          = 5


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
        psram_phy = HyperRAMPHY(bus=ram_bus)
        psram = HyperRAMInterface(phy=psram_phy.phy)
        m.submodules += [psram_phy, psram]

        psram_address = registers.add_register(REGISTER_RAM_ADDR)

        m.submodules.read_fifo  = read_fifo  = SyncFIFO(width=16, depth=32)
        m.submodules.write_fifo = write_fifo = SyncFIFO(width=16, depth=32)
        registers.add_sfr(REGISTER_RAM_FIFO,
            read=read_fifo.r_data,
            read_strobe=read_fifo.r_en,
            write_signal=write_fifo.w_data,
            write_strobe=write_fifo.w_en)

        register_space = registers.add_register(REGISTER_RAM_REGISTER_SPACE, size=1)

        start_read = Signal()
        start_write = Signal()
        registers.add_sfr(REGISTER_RAM_START,
            read_strobe=start_read,
            write_strobe=start_write)

        # Hook up our PSRAM.
        m.d.comb += [
            ram_bus.reset          .eq(0),
            psram.single_page      .eq(0),
            psram.register_space   .eq(register_space),
            psram.final_word       .eq(1),
            psram.perform_write    .eq(start_write),
            psram.start_transfer   .eq(start_read | start_write),
            psram.address          .eq(psram_address),
            psram.write_data       .eq(write_fifo.r_data),
            read_fifo.w_data       .eq(psram.read_data),
            read_fifo.w_en         .eq(psram.new_data_ready),
        ]

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    test = top_level_cli(HyperRAMDiagnostic)

    # Create a debug and ILA connection.
    dut = ApolloDebugger()
    logging.info(f"Connected to onboard dut; hardware revision r{dut.major}.{dut.minor} (s/n: {dut.serial_number}).")

    logging.info("Running basic HyperRAM diagnostics.")

    iterations = 1

    passes   = 0
    failures = 0
    failed_tests = set()

    def read_hyperram_register(addr):
        dut.registers.register_write(REGISTER_RAM_REGISTER_SPACE, 1)
        dut.registers.register_write(REGISTER_RAM_ADDR, addr)
        dut.registers.register_read(REGISTER_RAM_START)
        time.sleep(0.1)
        return dut.registers.register_read(REGISTER_RAM_FIFO)

    def test_id_read():
        return read_hyperram_register(0x0) in (0x0c81, 0x0c86)

    def test_config_read():
        return read_hyperram_register(0x800) in (0x8f1f, 0x8f2f)

    def test_mem_readback():
        dut.registers.register_write(REGISTER_RAM_REGISTER_SPACE, 0)
        dut.registers.register_write(REGISTER_RAM_FIFO, 0xabcd)
        for addr in range(10):
            # Set address.
            dut.registers.register_write(REGISTER_RAM_ADDR, addr)

            # Write data
            dut.registers.register_write(REGISTER_RAM_START, 1)
            time.sleep(0.1)

            # Read data
            dut.registers.register_read(REGISTER_RAM_START)
            time.sleep(0.1)
            result = dut.registers.register_read(REGISTER_RAM_FIFO)
            print(f"{result=:x} {addr=}")

        return True

    # Run each of our tests.
    for test in (test_id_read, test_config_read, test_mem_readback):
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
