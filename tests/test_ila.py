#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.interface.spi import SPIGatewareTestCase
from luna.gateware.test import LunaGatewareTestCase, sync_test_case

from amaranth import Signal, Cat
from luna.gateware.debug.ila import IntegratedLogicAnalyzer, StreamILA, SyncSerialILA

class IntegratedLogicAnalyzerTest(LunaGatewareTestCase):

    def instantiate_dut(self):
        self.input_a = Signal()
        self.input_b = Signal(30)
        self.input_c = Signal()

        return IntegratedLogicAnalyzer(
            signals=[self.input_a, self.input_b, self.input_c],
            sample_depth = 32
        )


    def initialize_signals(self):
        yield self.input_a .eq(0)
        yield self.input_b .eq(0)
        yield self.input_c .eq(0)


    def provide_all_signals(self, value):
        all_signals = Cat(self.input_a, self.input_b, self.input_c)
        yield all_signals.eq(value)


    def assert_sample_value(self, address, value):
        """ Helper that asserts a ILA sample has a given value. """

        yield self.dut.captured_sample_number.eq(address)
        yield
        # Delay a clock to allow the block ram to latch the new value
        yield
        try:
            self.assertEqual((yield self.dut.captured_sample), value)
            return
        except AssertionError:
            pass

        # Generate an appropriate exception.
        actual_value = (yield self.dut.captured_sample)
        message = "assertion failed: at address 0x{:08x}: {:08x} != {:08x} (expected)".format(address, actual_value, value)
        raise AssertionError(message)


    @sync_test_case
    def test_sampling(self):

        # Quick helper that generates simple, repetitive samples.
        def sample_value(i):
            return i | (i << 8) | (i << 16) | (0xFF << 24)

        yield from self.provide_all_signals(0xDEADBEEF)
        yield

        # Before we trigger, we shouldn't be capturing any samples,
        # and we shouldn't be complete.
        self.assertEqual((yield self.dut.sampling), 0)
        self.assertEqual((yield self.dut.complete), 0)

        # Advance a bunch of cycles, and ensure we don't start sampling.
        yield from self.advance_cycles(10)
        self.assertEqual((yield self.dut.sampling), 0)

        # Set a new piece of data for a couple of cycles.
        yield from self.provide_all_signals(0x01234567)
        yield
        yield from self.provide_all_signals(0x89ABCDEF)
        yield

        # Finally, trigger the capture.
        yield from self.provide_all_signals(sample_value(0))
        yield from self.pulse(self.dut.trigger, step_after=False)

        yield from self.provide_all_signals(sample_value(1))
        yield

        # After we pulse our trigger strobe, we should be sampling.
        self.assertEqual((yield self.dut.sampling), 1)

        # Populate the memory with a variety of interesting signals;
        # and continue afterwards for a couple of cycles to make sure
        # these don't make it into our sample buffer.
        for i in range(2, 34):
            yield from self.provide_all_signals(sample_value(i))
            yield

        # We now should be done with our sampling.
        self.assertEqual((yield self.dut.sampling), 0)
        self.assertEqual((yield self.dut.complete), 1)

        # Validate the memory values that were captured.
        for i in range(32):
            yield from self.assert_sample_value(i, sample_value(i))

        # All of those reads shouldn't change our completeness.
        self.assertEqual((yield self.dut.sampling), 0)
        self.assertEqual((yield self.dut.complete), 1)


class SyncSerialReadoutILATest(SPIGatewareTestCase):

    def instantiate_dut(self):
        self.input_signal = Signal(12)
        return SyncSerialILA(
            signals=[self.input_signal],
            sample_depth=16,
            clock_polarity=1,
            clock_phase=0
        )

    def initialize_signals(self):
        yield self.input_signal.eq(0xF00)

    @sync_test_case
    def test_spi_readout(self):
        input_signal = self.input_signal

        # Trigger the test while offering our first sample.
        yield
        yield from self.pulse(self.dut.trigger, step_after=False)

        # Provide the remainder of our samples.
        for i in range(1, 16):
            yield input_signal.eq(0xF00 | i)
            yield

        # Wait a few cycles to account for delays in
        # the sampling pipeline.
        yield from self.advance_cycles(5)

        # We've now captured a full set of samples.
        # We'll test reading them out.
        self.assertEqual((yield self.dut.complete), 1)

        # Start the transaction, and exchange 16 bytes of data.
        yield self.dut.spi.cs.eq(1)
        yield

        # Read our our result over SPI...
        data = yield from self.spi_exchange_data(b"\0" * 32)

        # ... and ensure it matches what was sampled.
        i = 0
        while data:
            datum = data[0:4]
            del data[0:4]

            expected = b"\x00\x00\x0f" + bytes([i])
            self.assertEqual(datum, expected)
            i += 1

class StreamILATest(LunaGatewareTestCase):

    def instantiate_dut(self):
        self.input_signal = Signal(12)
        return StreamILA(
            signals=[self.input_signal],
            sample_depth=16
        )

    def initialize_signals(self):
        yield self.input_signal.eq(0xF00)

    @sync_test_case
    def test_stream_readout(self):
        input_signal = self.input_signal
        stream = self.dut.stream

        # Trigger the ILA with the first sample
        yield
        yield from self.pulse(self.dut.trigger, step_after=False)

        # Fill up the ILA with the remaining samples
        for i in range(1, 16):
            yield input_signal.eq(0xF00 | i)
            yield

        # Wait a few cycles to allow the ILA to fully finish processing
        yield from self.advance_cycles(6)
        # Stream should now be presenting valid data
        self.assertEqual((yield stream.valid), 1)

        # Now we want to stream out the samples from the ILA
        yield stream.ready.eq(1)
        yield
        self.assertEqual((yield stream.first), 1)

        # Read out data from the stream until it signals completion
        data = []
        while not (yield stream.last):
            if (yield stream.valid):
                data.append((yield stream.payload))
            yield

        # Match read data to what should have been sampled
        for i, datum in enumerate(data):
            self.assertEqual(datum, 0xF00 | i)
