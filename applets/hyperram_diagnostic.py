#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import time
import logging
import random

from prompt_toolkit import HTML
from prompt_toolkit import print_formatted_text as pprint

from amaranth import Signal, Elaboratable, Module
from amaranth.lib.fifo import SyncFIFO

from luna                             import top_level_cli
from apollo_fpga                      import ApolloDebugger
from luna.gateware.interface.jtag     import JTAGRegisterInterface
from luna.gateware.interface.psram    import HyperRAMPHY, HyperRAMInterface, HyperRAMDQSInterface, HyperRAMDQSPHY

REGISTER_RAM_REGISTER_SPACE = 1
REGISTER_RAM_ADDR           = 2
REGISTER_RAM_READ_LENGTH    = 3
REGISTER_RAM_FIFO           = 4
REGISTER_RAM_START          = 5

DQS = False
REG_WIDTH = 32 if DQS else 16
REG_SHIFT = 16 if DQS else 0

class HyperRAMDiagnostic(Elaboratable):
    """
    Temporary gateware that evaluates HyperRAM skews.
    """


    def elaborate(self, platform):
        m = Module()

        clock_frequencies = platform.DEFAULT_CLOCK_FREQUENCIES_MHZ

        #
        # HyperRAM test connections.
        #
        if DQS:
            clock_frequencies = {
                "fast": 120,
                "sync": 60,
                "usb":  60,
            }
            ram_bus = platform.request('ram', dir={'rwds':'-', 'dq':'-', 'cs':'-'})
            psram_phy = HyperRAMDQSPHY(bus=ram_bus)
            psram = HyperRAMDQSInterface(phy=psram_phy.phy)
        else:
            ram_bus = platform.request('ram')
            psram_phy = HyperRAMPHY(bus=ram_bus)
            psram = HyperRAMInterface(phy=psram_phy.phy)

        m.submodules += [psram_phy, psram]

        # Generate our clock domains.
        clocking = platform.clock_domain_generator(clock_frequencies=clock_frequencies)
        m.submodules.clocking = clocking

        # Create a set of registers...
        registers = JTAGRegisterInterface(address_size=7, default_read_value=0xDEADBEEF)
        m.submodules.registers = registers

        psram_address = registers.add_register(REGISTER_RAM_ADDR)
        read_length   = registers.add_register(REGISTER_RAM_READ_LENGTH, reset=1)

        m.submodules.read_fifo  = read_fifo  = SyncFIFO(width=REG_WIDTH, depth=32)
        m.submodules.write_fifo = write_fifo = SyncFIFO(width=REG_WIDTH, depth=32)
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

        read_counter = Signal.like(read_length)
        final_word = Signal()
        m.d.comb += final_word.eq(1)
        with m.FSM() as fsm:
            with m.State("IDLE"):
                with m.If(start_read):
                    m.d.sync += read_counter.eq(read_length)
                    m.next = "READ"

                with m.If(start_write):
                    m.next = "WRITE"

            with m.State("READ"):
                m.d.comb += final_word.eq(read_counter == 1)
                with m.If(psram.read_ready):
                    m.d.sync += read_counter.eq(read_counter - 1)
                with m.If(psram.idle):
                    m.next = "IDLE"

            with m.State("WRITE"):
                m.d.comb += final_word.eq(write_fifo.level == 1)
                with m.If(psram.idle):
                    m.next = "IDLE"


        # Hook up our PSRAM.
        m.d.comb += [
            ram_bus.reset.o        .eq(0),
            psram.single_page      .eq(0),
            psram.register_space   .eq(register_space),
            psram.final_word       .eq(final_word),
            psram.perform_write    .eq(start_write),
            psram.start_transfer   .eq(start_read | start_write),
            psram.address          .eq(psram_address),
            psram.write_data       .eq(write_fifo.r_data),
            read_fifo.w_data       .eq(psram.read_data),
            read_fifo.w_en         .eq(psram.read_ready),
            write_fifo.r_en        .eq(psram.write_ready),
        ]

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    test = top_level_cli(HyperRAMDiagnostic)

    # Create a debug and ILA connection.
    dut = ApolloDebugger()
    logging.info(f"Connected to onboard dut; hardware revision r{dut.major}.{dut.minor} (s/n: {dut.serial_number}).")

    if DQS:
        logging.info("Running basic HyperRAM diagnostics, using DQS implementation.")
    else:
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
        return dut.registers.register_read(REGISTER_RAM_FIFO) >> REG_SHIFT

    def test_id_read():
        return read_hyperram_register(0x0) in (0x0c81, 0x0c86)

    def test_config_read():
        return read_hyperram_register(0x800) in (0x8f1f, 0x8f2f)

    def test_mem_readback():
        dut.registers.register_write(REGISTER_RAM_REGISTER_SPACE, 0)

        data = [random.randint(0, int(2**REG_WIDTH)) for _ in range(10)]

        # Fill write FIFO.
        for d in data:
            dut.registers.register_write(REGISTER_RAM_FIFO, d)

        # Initiate burst write at address 0.
        dut.registers.register_write(REGISTER_RAM_ADDR, 0)
        dut.registers.register_write(REGISTER_RAM_START, 1)

        # Set read length & initiate read.
        dut.registers.register_write(REGISTER_RAM_READ_LENGTH, 10)
        dut.registers.register_read(REGISTER_RAM_START)

        # Verify data.
        for addr in range(len(data)):
            result = dut.registers.register_read(REGISTER_RAM_FIFO)
            if result != data[addr]:
                print(f"{result=:x} {data[addr]=:x} {addr=}")
                return False

        return True

    # Run each of our tests.
    for test in (test_id_read, test_config_read, test_mem_readback):
        for i in range(iterations):

            if test():
                pprint(".", end="")
                passes += 1
            else:
                pprint("✗", end="")

                failures += 1
                failed_tests.add(test)

    fail_text = "<red>✗ FAILED</red>"
    pass_text = "<green>✓ PASSED</green>"
    pprint(HTML("\n\n<b><u>Results:</u></b>"))

    pprint(HTML(f"    ID READ:      {fail_text if test_id_read in failed_tests else pass_text}"))
    pprint(HTML(f"    CONFIG READ:  {fail_text if test_config_read in failed_tests else pass_text}"))
    pprint(HTML(f"    MEM READBACK: {fail_text if test_mem_readback in failed_tests else pass_text}"))


    print(f"\nDiagnostics completed with {passes} passes and {failures} failures.\n")
