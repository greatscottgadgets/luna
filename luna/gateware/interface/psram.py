#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Interfaces to LUNA's PSRAM chips."""

import unittest

from amaranth import Signal, Module, Cat, Elaboratable, Record, ClockDomain, ClockSignal
from amaranth.hdl.rec import DIR_FANIN, DIR_FANOUT

from ..utils.io   import delay
from ..test.utils import LunaGatewareTestCase, sync_test_case


class HyperBus(Record):
    """ Record representing an HyperBus (DDR-ish connection for HyperRAM). """

    def __init__(self):
        super().__init__([
            ('clk', 1, DIR_FANOUT),
            ('dq',
                ('i', 8, DIR_FANIN),
                ('o', 8, DIR_FANOUT),
                ('e', 1, DIR_FANOUT),
            ),
            ('rwds',
                ('i', 1, DIR_FANIN),
                ('o', 1, DIR_FANOUT),
                ('e', 1, DIR_FANOUT),
            ),
            ('cs',     1, DIR_FANOUT),
            ('reset',  1, DIR_FANOUT)
        ])



class HyperRAMInterface(Elaboratable):
    """ Gateware interface to HyperRAM series self-refreshing DRAM chips.

    I/O port:
        B: bus              -- The primary physical connection to the DRAM chip.
        I: reset            -- An active-high signal used to provide a prolonged reset upon configuration.

        I: address[32]      -- The address to be targeted by the given operation.
        I: register_space   -- When set to 1, read and write requests target registers instead of normal RAM.
        I: perform_write    -- When set to 1, a transfer request is viewed as a write, rather than a read.
        I: single_page      -- If set, data accesses will wrap around to the start of the current page when done.
        I: start_transfer   -- Strobe that goes high for 1-8 cycles to request a read operation.
                               [This added duration allows other clock domains to easily perform requests.]
        I: final_word       -- Flag that indicates the current word is the last word of the transaction.

        O: read_data[16]    -- word that holds the 16 bits most recently read from the PSRAM
        I: write_data[16]   -- word that accepts the data to output during this transaction

        O: idle             -- High whenever the transmitter is idle (and thus we can start a new piece of data.)
        O: new_data_ready   -- Strobe that indicates when new data is ready for reading
    """

    LOW_LATENCY_EDGES  = 6
    HIGH_LATENCY_EDGES = 14

    def __init__(self, *, bus, in_skew=None, out_skew=None, clock_skew=None):
        """
        Parmeters:
            bus           -- The RAM record that should be connected to this RAM chip.
            data_skews    -- If provided, adds an input delay to each line of the data input.
                             Can be provided as a single delay number, or an interable of eight
                             delays to separately delay each of the input lines.
        """

        self.in_skew    = in_skew
        self.out_skew   = out_skew
        self.clock_skew = clock_skew

        #
        # I/O port.
        #
        self.bus              = bus
        self.reset            = Signal()

        # Control signals.
        self.address          = Signal(32)
        self.register_space   = Signal()
        self.perform_write    = Signal()
        self.single_page      = Signal()
        self.start_transfer   = Signal()
        self.final_word       = Signal()

        # Status signals.
        self.idle             = Signal()
        self.new_data_ready   = Signal()

        # Data signals.
        self.read_data        = Signal(16)
        self.write_data       = Signal(16)


    def elaborate(self, platform):
        m = Module()

        #
        # Delayed input and output.
        #

        if self.in_skew is not None:
            data_in = delay(m, self.bus.dq.i, self.in_skew)
        else:
            data_in = self.bus.dq.i

        data_oe = self.bus.dq.oe
        if self.out_skew is not None:
            data_out = Signal.like(self.bus.dq.o)
            delay(m, data_out, self.out_skew, out=self.bus.dq.o)
        else:
            data_out = self.bus.dq.o


        #
        # Transaction clock generator.
        #
        advance_clock  = Signal()
        reset_clock    = Signal()

        if self.clock_skew is not None:
            out_clock = Signal()
            delay(m, out_clock, self.clock_skew, out=self.bus.clk)
        else:
            out_clock = self.bus.clk

        with m.If(reset_clock):
            m.d.sync += out_clock.eq(0)
        with m.Elif(advance_clock):
            m.d.sync += out_clock.eq(~out_clock)


        #
        # Latched control/addressing signals.
        #
        is_read         = Signal()
        is_register     = Signal()
        current_address = Signal(32)
        is_multipage    = Signal()

        #
        # FSM datapath signals.
        #

        # Tracks whether we need to add an extra latency period between our
        # command and the data body.
        extra_latency   = Signal()

        # Tracks how many cycles of latency we have remaining between a command
        # and the relevant data stages.
        latency_edges_remaining  = Signal(range(0, self.HIGH_LATENCY_EDGES + 1))

        # One cycle delayed version of RWDS.
        # This is used to detect edges in RWDS during reads, which semantically mean
        # we should accept new data.
        last_rwds = Signal.like(self.bus.rwds.i)
        m.d.sync += last_rwds.eq(self.bus.rwds.i)

        # Create a sync-domain version of our 'new data ready' signal.
        new_data_ready = self.new_data_ready

        #
        # Core operation FSM.
        #

        # Provide defaults for our control/status signals.
        m.d.sync += [
            advance_clock       .eq(1),
            reset_clock         .eq(0),
            new_data_ready      .eq(0),

            self.bus.cs         .eq(1),
            self.bus.rwds.oe    .eq(0),
            self.bus.dq.oe      .eq(0),
        ]

        with m.FSM() as fsm:

            # IDLE state: waits for a transaction request
            with m.State('IDLE'):
                m.d.sync += reset_clock      .eq(1)
                m.d.comb += self.idle        .eq(1)

                # Once we have a transaction request, latch in our control
                # signals, and assert our chip-select.
                with m.If(self.start_transfer):
                    m.next = 'LATCH_RWDS'

                    m.d.sync += [
                        is_read             .eq(~self.perform_write),
                        is_register         .eq(self.register_space),
                        is_multipage        .eq(~self.single_page),
                        current_address     .eq(self.address),
                    ]

                with m.Else():
                    m.d.sync += self.bus.cs.eq(0)


            # LATCH_RWDS -- latch in the value of the RWDS signal, which determines
            # our read/write latency. Note that we advance the clock in this state,
            # as our out-of-phase clock signal will output the relevant data before
            # the next edge can occur.
            with m.State("LATCH_RWDS"):
                m.d.sync += extra_latency.eq(self.bus.rwds.i),
                m.next="SHIFT_COMMAND0"


            # Commands, in order of bytes sent:
            #   - WRBAAAAA
            #     W         => selects read or write; 1 = read, 0 = write
            #      R        => selects register or memory; 1 = register, 0 = memory
            #       B       => selects burst behavior; 0 = wrapped, 1 = linear
            #        AAAAA  => address bits [27:32]
            #
            #   - AAAAAAAA  => address bits [19:27]
            #   - AAAAAAAA  => address bits [11:19]
            #   - AAAAAAAA  => address bits [ 3:16]
            #   - 00000000  => [reserved]
            #   - 00000AAA  => address bits [ 0: 3]

            # SHIFT_COMMANDx -- shift each of our command bytes out
            with m.State('SHIFT_COMMAND0'):
                m.next = 'SHIFT_COMMAND1'

                # Build our composite command byte.
                command_byte = Cat(
                    current_address[27:32],
                    is_multipage,
                    is_register,
                    is_read
                )

                # Output our first byte of our command.
                m.d.sync += [
                    data_out  .eq(command_byte),
                    data_oe   .eq(1)
                ]

            # Note: it's felt that this is more readable with each of these
            # states defined explicitly. If you strongly disagree, feel free
            # to PR a for-loop, here.~


            with m.State('SHIFT_COMMAND1'):
                m.d.sync += [
                    data_out  .eq(current_address[19:27]),
                    data_oe   .eq(1)
                ]
                m.next = 'SHIFT_COMMAND2'

            with m.State('SHIFT_COMMAND2'):
                m.d.sync += [
                    data_out  .eq(current_address[11:19]),
                    data_oe   .eq(1)
                ]
                m.next = 'SHIFT_COMMAND3'

            with m.State('SHIFT_COMMAND3'):
                m.d.sync += [
                    data_out  .eq(current_address[ 3:16]),
                    data_oe   .eq(1)
                ]
                m.next = 'SHIFT_COMMAND4'

            with m.State('SHIFT_COMMAND4'):
                m.d.sync += [
                    data_out  .eq(0),
                    data_oe   .eq(1)
                ]
                m.next = 'SHIFT_COMMAND5'

            with m.State('SHIFT_COMMAND5'):
                m.d.sync += [
                    data_out  .eq(current_address[0:3]),
                    data_oe   .eq(1)
                ]

                # If we have a register write, we don't need to handle
                # any latency. Move directly to our SHIFT_DATA state.
                with m.If(is_register & ~is_read):
                    m.next = 'WRITE_DATA_MSB'

                # Otherwise, react with either a short period of latency
                # or a longer one, depending on what the RAM requested via
                # RWDS.
                with m.Else():
                    m.next = "HANDLE_LATENCY"

                    with m.If(extra_latency):
                        m.d.sync += latency_edges_remaining.eq(self.HIGH_LATENCY_EDGES)
                    with m.Else():
                        m.d.sync += latency_edges_remaining.eq(self.LOW_LATENCY_EDGES)


            # HANDLE_LATENCY -- applies clock edges until our latency period is over.
            with m.State('HANDLE_LATENCY'):
                m.d.sync += latency_edges_remaining.eq(latency_edges_remaining - 1)

                with m.If(latency_edges_remaining == 0):
                    with m.If(is_read):
                        m.next = 'READ_DATA_MSB'
                    with m.Else():
                        m.next = 'WRITE_DATA_MSB'


            # STREAM_DATA_MSB -- scans in or out the first byte of data
            with m.State('READ_DATA_MSB'):

                # If RWDS has changed, the host has just sent us new data.
                with m.If(self.bus.rwds.i != last_rwds):
                    m.d.sync += self.read_data[8:16].eq(data_in)
                    m.next = 'READ_DATA_LSB'


            # STREAM_DATA_LSB -- scans in or out the second byte of data
            with m.State('READ_DATA_LSB'):

                # If RWDS has changed, the host has just sent us new data.
                # Sample it, and indicate that we now have a valid piece of new data.
                with m.If(self.bus.rwds.i != last_rwds):
                    m.d.sync += [
                        self.read_data[0:8]  .eq(data_in),
                        new_data_ready       .eq(1)
                    ]

                    # If our controller is done with the transcation, end it.
                    with m.If(self.final_word):
                        m.next = 'RECOVERY'
                        m.d.sync += advance_clock.eq(0)

                    with m.Else():
                        #m.next = 'READ_DATA_MSB'
                        m.next = 'RECOVERY'


            # WRITE_DATA_MSB -- write the first of our two bytes of data to the to the PSRAM
            with m.State("WRITE_DATA_MSB"):
                m.d.sync += [
                    data_out  .eq(self.write_data[8:16]),
                    data_oe   .eq(1),
                ]
                m.next = "WRITE_DATA_LSB"


            # WRITE_DATA_LSB -- write the first of our two bytes of data to the to the PSRAM
            with m.State("WRITE_DATA_LSB"):
                m.d.sync += [
                    data_out  .eq(self.write_data[0:8]),
                    data_oe   .eq(1),
                ]
                m.next = "WRITE_DATA_LSB"

                # If we just finished a register write, we're done -- there's no need for recovery.
                with m.If(is_register):
                    m.next = 'IDLE'
                    m.d.sync += advance_clock.eq(0)

                with m.Elif(self.final_word):
                    m.next = 'RECOVERY'
                    m.d.sync += advance_clock.eq(0)

                with m.Else():
                    #m.next = 'READ_DATA_MSB'
                    m.next = 'RECOVERY'


            # RECOVERY state: wait for the required period of time before a new transaction
            with m.State('RECOVERY'):
                m.d.sync += [
                    self.bus.cs   .eq(0),
                    advance_clock .eq(0)
                ]

                # TODO: implement recovery
                m.next = 'IDLE'



        return m


class TestHyperRAMInterface(LunaGatewareTestCase):

    def instantiate_dut(self):
        # Create a record that recreates the layout of our RAM signals.
        self.ram_signals = Record([
            ("clk",   1),
            ("clkN",  1),
            ("dq",   [("i",  8), ("o",  8), ("oe", 1)]),
            ("rwds", [("i",  1), ("o",  1), ("oe", 1)]),
            ("cs",    1),
            ("reset", 1)
        ])

        # Create our HyperRAM interface...
        return HyperRAMInterface(bus=self.ram_signals)


    def assert_clock_pulses(self, times=1):
        """ Function that asserts we get a specified number of clock pulses. """

        for _ in range(times):
            yield
            self.assertEqual((yield self.ram_signals.clk), 1)
            yield
            self.assertEqual((yield self.ram_signals.clk), 0)


    @sync_test_case
    def test_register_write(self):

        # Before we transact, CS should be de-asserted, and RWDS and DQ should be undriven.
        yield
        self.assertEqual((yield self.ram_signals.cs),      0)
        self.assertEqual((yield self.ram_signals.dq.oe),   0)
        self.assertEqual((yield self.ram_signals.rwds.oe), 0)

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
        self.assertEqual((yield self.ram_signals.cs),  1)
        self.assertEqual((yield self.ram_signals.clk), 0)

        # Drop our "start request" line somewhere during the transaction;
        # so we don't immediately go into the next transfer.
        yield self.dut.start_transfer.eq(0)

        # We should then move to shifting out our first command word,
        # which means we're driving DQ with the first word of our command.
        yield
        yield
        self.assertEqual((yield self.ram_signals.cs),       1)
        self.assertEqual((yield self.ram_signals.clk),      1)
        self.assertEqual((yield self.ram_signals.dq.oe),    1)
        self.assertEqual((yield self.ram_signals.dq.o),  0x60)

        # Next, on the falling edge of our clock, the next byte should be presented.
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)
        self.assertEqual((yield self.ram_signals.dq.o),  0x17)

        # This should continue until we've shifted out a full command.
        yield
        self.assertEqual((yield self.ram_signals.clk),      1)
        self.assertEqual((yield self.ram_signals.dq.o),  0x79)
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)
        self.assertEqual((yield self.ram_signals.dq.o),  0x9B)
        yield
        self.assertEqual((yield self.ram_signals.clk),      1)
        self.assertEqual((yield self.ram_signals.dq.o),  0x00)
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)
        self.assertEqual((yield self.ram_signals.dq.o),  0x05)

        # Check that we've been driving our output this whole time,
        # and haven't been driving RWDS.
        self.assertEqual((yield self.ram_signals.dq.oe),    1)
        self.assertEqual((yield self.ram_signals.rwds.oe),  0)
        yield

        # For a _register_ write, there shouldn't be latency period.
        # This means we should continue driving DQ...
        self.assertEqual((yield self.ram_signals.dq.oe),    1)
        self.assertEqual((yield self.ram_signals.rwds.oe),  0)

        self.assertEqual((yield self.ram_signals.clk),      1)
        self.assertEqual((yield self.ram_signals.dq.o),  0xBE)
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)
        self.assertEqual((yield self.ram_signals.dq.o),  0xEF)



    @sync_test_case
    def test_register_read(self):

        # Before we transact, CS should be de-asserted, and RWDS and DQ should be undriven.
        yield
        self.assertEqual((yield self.ram_signals.cs),      0)
        self.assertEqual((yield self.ram_signals.dq.oe),   0)
        self.assertEqual((yield self.ram_signals.rwds.oe), 0)

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
        self.assertEqual((yield self.ram_signals.cs),  1)
        self.assertEqual((yield self.ram_signals.clk), 0)

        # Drop our "start request" line somewhere during the transaction;
        # so we don't immediately go into the next transfer.
        yield self.dut.start_transfer.eq(0)

        # We should then move to shifting out our first command word,
        # which means we're driving DQ with the first word of our command.
        yield
        yield
        self.assertEqual((yield self.ram_signals.cs),       1)
        self.assertEqual((yield self.ram_signals.clk),      1)
        self.assertEqual((yield self.ram_signals.dq.oe),    1)
        self.assertEqual((yield self.ram_signals.dq.o),  0xe0)

        # Next, on the falling edge of our clock, the next byte should be presented.
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)
        self.assertEqual((yield self.ram_signals.dq.o),  0x17)

        # This should continue until we've shifted out a full command.
        yield
        self.assertEqual((yield self.ram_signals.clk),      1)
        self.assertEqual((yield self.ram_signals.dq.o),  0x79)
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)
        self.assertEqual((yield self.ram_signals.dq.o),  0x9B)
        yield
        self.assertEqual((yield self.ram_signals.clk),      1)
        self.assertEqual((yield self.ram_signals.dq.o),  0x00)
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)
        self.assertEqual((yield self.ram_signals.dq.o),  0x05)

        # Check that we've been driving our output this whole time,
        # and haven't been driving RWDS.
        self.assertEqual((yield self.ram_signals.dq.oe),    1)
        self.assertEqual((yield self.ram_signals.rwds.oe),  0)

        # Once we finish scanning out the word, we should stop driving
        # the data lines, and should finish two latency periods before
        # sending any more data.
        yield
        self.assertEqual((yield self.ram_signals.dq.oe),    0)
        self.assertEqual((yield self.ram_signals.rwds.oe),  0)
        self.assertEqual((yield self.ram_signals.clk),      1)

        # By this point, the RAM will drive RWDS low.
        yield self.ram_signals.rwds.i.eq(0)

        # Ensure the clock still ticking...
        yield
        self.assertEqual((yield self.ram_signals.clk),      0)

        # ... and remains so for the remainder of the latency period.
        yield from self.assert_clock_pulses(6)

        # Now, shift in a pair of data words.
        yield self.ram_signals.dq.i.eq(0xCA)
        yield self.ram_signals.rwds.i.eq(1)
        yield
        yield self.ram_signals.dq.i.eq(0xFE)
        yield self.ram_signals.rwds.i.eq(0)
        yield
        yield

        # Once this finished, we should have a result on our data out.
        self.assertEqual((yield self.dut.read_data),      0xCAFE)
        self.assertEqual((yield self.dut.new_data_ready), 1)

        yield
        self.assertEqual((yield self.ram_signals.cs),      0)
        self.assertEqual((yield self.ram_signals.dq.oe),   0)
        self.assertEqual((yield self.ram_signals.rwds.oe), 0)

        # Ensure that our clock drops back to '0' during idle cycles.
        yield from self.advance_cycles(2)
        self.assertEqual((yield self.ram_signals.clk),     0)

        # TODO: test recovery time

if __name__ == "__main__":
    unittest.main()

