#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test.utils import LunaGatewareTestCase, sync_test_case

from luna.gateware.interface.psram import HyperBusPHY, HyperRAMInterface

class TestHyperRAMInterface(LunaGatewareTestCase):

    def instantiate_dut(self):
        # Create a record that recreates the layout of our RAM signals.
        self.ram_signals = HyperBusPHY()

        # Create our HyperRAM interface...
        return HyperRAMInterface(phy=self.ram_signals)


    def assert_clock_pulses(self, times=1):
        """ Function that asserts we get a specified number of clock pulses. """

        for _ in range(times):
            yield
            self.assertEqual((yield self.ram_signals.clk_en), 1)


    @sync_test_case
    def test_register_write(self):

        # Before we transact, CS should be de-asserted, and RWDS and DQ should be undriven.
        yield
        self.assertEqual((yield self.ram_signals.cs),      0)
        self.assertEqual((yield self.ram_signals.dq.e),    0)
        self.assertEqual((yield self.ram_signals.rwds.e),  0)

        yield from self.advance_cycles(10)
        self.assertEqual((yield self.ram_signals.cs),      0)

        # Request a register write to ID register 0.
        yield self.dut.perform_write  .eq(1)
        yield self.dut.register_space .eq(1)
        yield self.dut.address        .eq(0x00BBCCDD)
        yield self.dut.start_transfer .eq(1)
        yield self.dut.final_word     .eq(1)
        yield self.dut.write_data     .eq(0xBEEF)

        # Simulate the RAM requesting a extended latency.
        yield self.ram_signals.rwds.i .eq(1)
        yield

        # Ensure that upon requesting, CS goes high, and our clock starts low.
        yield
        self.assertEqual((yield self.ram_signals.cs),     1)
        self.assertEqual((yield self.ram_signals.clk_en), 0)

        # Drop our "start request" line somewhere during the transaction;
        # so we don't immediately go into the next transfer.
        yield self.dut.start_transfer.eq(0)

        # We should then move to shifting out our first command word,
        # which means we're driving DQ with the first word of our command.
        yield
        yield
        self.assertEqual((yield self.ram_signals.cs),       1)
        self.assertEqual((yield self.ram_signals.clk_en),   1)
        self.assertEqual((yield self.ram_signals.dq.e),     1)
        self.assertEqual((yield self.ram_signals.dq.o),  0x6017)

        # This should continue until we've shifted out a full command.
        yield
        self.assertEqual((yield self.ram_signals.dq.o),  0x799B)
        yield
        self.assertEqual((yield self.ram_signals.dq.o),  0x0005)

        # Check that we've been driving our output this whole time,
        # and haven't been driving RWDS.
        self.assertEqual((yield self.ram_signals.dq.e),    1)
        self.assertEqual((yield self.ram_signals.rwds.e),  0)
        yield

        # For a _register_ write, there shouldn't be latency period.
        # This means we should continue driving DQ...
        self.assertEqual((yield self.ram_signals.dq.e),    1)
        self.assertEqual((yield self.ram_signals.rwds.e),  0)
        self.assertEqual((yield self.ram_signals.dq.o),  0xBEEF)



    @sync_test_case
    def test_register_read(self):

        # Before we transact, CS should be de-asserted, and RWDS and DQ should be undriven.
        yield
        self.assertEqual((yield self.ram_signals.cs),      0)
        self.assertEqual((yield self.ram_signals.dq.e),   0)
        self.assertEqual((yield self.ram_signals.rwds.e), 0)

        yield from self.advance_cycles(10)
        self.assertEqual((yield self.ram_signals.cs),      0)

        # Request a register read of ID register 0.
        yield self.dut.perform_write  .eq(0)
        yield self.dut.register_space .eq(1)
        yield self.dut.address        .eq(0x00BBCCDD)
        yield self.dut.start_transfer .eq(1)
        yield self.dut.final_word     .eq(1)

        # Simulate the RAM requesting a extended latency.
        yield self.ram_signals.rwds.i .eq(1)
        yield

        # Ensure that upon requesting, CS goes high, and our clock starts low.
        yield
        self.assertEqual((yield self.ram_signals.cs),     1)
        self.assertEqual((yield self.ram_signals.clk_en), 0)

        # Drop our "start request" line somewhere during the transaction;
        # so we don't immediately go into the next transfer.
        yield self.dut.start_transfer.eq(0)

        # We should then move to shifting out our first command word,
        # which means we're driving DQ with the first word of our command.
        yield
        yield
        self.assertEqual((yield self.ram_signals.cs),         1)
        self.assertEqual((yield self.ram_signals.clk_en),     1)
        self.assertEqual((yield self.ram_signals.dq.e),       1)
        self.assertEqual((yield self.ram_signals.dq.o),  0xe017)

        # This should continue until we've shifted out a full command.
        yield
        self.assertEqual((yield self.ram_signals.dq.o),  0x799B)
        yield
        self.assertEqual((yield self.ram_signals.dq.o),  0x0005)

        # Check that we've been driving our output this whole time,
        # and haven't been driving RWDS.
        self.assertEqual((yield self.ram_signals.dq.e),    1)
        self.assertEqual((yield self.ram_signals.rwds.e),  0)

        # Once we finish scanning out the word, we should stop driving
        # the data lines, and should finish two latency periods before
        # sending any more data.
        yield
        self.assertEqual((yield self.ram_signals.dq.e),    0)
        self.assertEqual((yield self.ram_signals.rwds.e),  0)
        self.assertEqual((yield self.ram_signals.clk_en),  1)

        # By this point, the RAM will drive RWDS low.
        yield self.ram_signals.rwds.i.eq(0)

        # Ensure the clock still ticking...
        yield
        self.assertEqual((yield self.ram_signals.clk_en),    1)

        # ... and remains so for the remainder of the latency period.
        yield from self.assert_clock_pulses(14)

        # Now, shift in a pair of data words.
        yield self.ram_signals.dq.i.eq(0xCAFE)
        yield self.ram_signals.rwds.i.eq(0b10)
        yield

        # Once this finished, we should have a result on our data out.
        self.assertEqual((yield self.dut.read_data),      0xCAFE)
        self.assertEqual((yield self.dut.read_ready    ), 1)

        yield
        yield
        self.assertEqual((yield self.ram_signals.cs),     0)
        self.assertEqual((yield self.ram_signals.dq.e),   0)
        self.assertEqual((yield self.ram_signals.rwds.e), 0)

        # Ensure that our clock drops back to '0' during idle cycles.
        yield from self.advance_cycles(2)
        self.assertEqual((yield self.ram_signals.clk_en),  0)

        # TODO: test recovery time

