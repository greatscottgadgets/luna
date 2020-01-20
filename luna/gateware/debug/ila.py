#
# This file is part of LUNA.
#
""" Integrated logic analysis helpers. """

import sys
import unittest

from abc import ABCMeta, abstractmethod

from nmigen          import Signal, Module, Cat, Elaboratable, Memory, ClockDomain, DomainRenamer
from nmigen.lib.cdc  import FFSynchronizer
from vcd             import VCDWriter

from ..util          import rising_edge_detector
from ..interface.spi import SPIDeviceInterface, SPIBus, SPIGatewareTestCase
from ..test.utils    import LunaGatewareTestCase, sync_test_case


class IntegratedLogicAnalyzer(Elaboratable):
    """ Super-simple integrated-logic-analyzer generator class for LUNA.

    I/O port:
        I: trigger                  -- A strobe that determines when we should start sampling.
        O: sampling                 -- Indicates when sampling is in progress.
        O: complete                 -- Indicates when sampling is complete and ready to be read.

        I: captured_sample_number[] -- Can be used to read the current sample number
        O: captured_sample          -- The sample corresponding to the relevant sample number.
                                       Can be broken apart by using Cat(*signals).
    """

    def __init__(self, *, signals, sample_depth, domain="sync", sample_rate=60e6, samples_pretrigger=1):
        """
        Parameters:
            signals            -- An iterable of signals that should be captured by the ILA.
            sample_depth       -- The depth of the desired buffer, in samples.
            domain             -- The clock domain in which the ILA should operate.
            sample_rate        -- Cosmetic indication of the sample rate. Used to format output.
            samples_pretrigger -- The number of our samples which should be captured _before_ the trigger.
                                  This also can act like an implicit synchronizer; so asynchronous inputs
                                  are allowed if this number is >= 2. Note that the trigger strobe is read
                                  on the rising edge of the
        """

        self.domain             = domain
        self.signals            = signals
        self.inputs             = Cat(*signals)
        self.sample_width       = len(self.inputs)
        self.sample_depth       = sample_depth
        self.samples_pretrigger = samples_pretrigger
        self.sample_rate        = sample_rate
        self.sample_period      = 1 / sample_rate

        #
        # Create a backing store for our samples.
        #
        self.mem = Memory(width=self.sample_width, depth=sample_depth, name="ila_buffer")


        #
        # I/O port
        #
        self.trigger  = Signal()
        self.sampling = Signal()
        self.complete = Signal()

        self.captured_sample_number = Signal(range(0, self.sample_depth))
        self.captured_sample        = Signal(self.sample_width)


    def elaborate(self, platform):
        m  = Module()

        # TODO: switch this to a single-port RAM

        # Memory ports.
        write_port = self.mem.write_port()
        read_port  = self.mem.read_port(domain='comb')
        m.submodules += [write_port, read_port]

        # If necessary, create synchronized versions of the relevant signals.
        if self.samples_pretrigger >= 2:
            delayed_inputs = Signal.like(self.inputs)
            m.submodules += FFSynchronizer(self.inputs,  delayed_inputs,
                stages=self.samples_pretrigger)
        elif self.samples_pretrigger == 1:
            delayed_inputs = Signal.like(self.inputs)
            m.d.sync += delayed_inputs.eq(self.inputs)
        else:
            delayed_inputs  = self.inputs

        # Counter that keeps track of our write position.
        write_position = Signal(range(0, self.sample_depth))

        # Set up our write port to capture the input signals,
        # and our read port to provide the output.
        m.d.comb += [
            write_port.data        .eq(delayed_inputs),
            write_port.addr        .eq(write_position),

            self.captured_sample   .eq(read_port.data),
            read_port.addr         .eq(self.captured_sample_number)
        ]

        self.test = Signal()
        m.d.comb += self.test.eq(read_port.addr)

        # Don't sample unless our FSM asserts our sample signal explicitly.
        m.d.sync += write_port.en.eq(0)

        with m.FSM() as fsm:

            m.d.comb += self.sampling.eq(~fsm.ongoing("IDLE"))

            # IDLE: wait for the trigger strobe
            with m.State('IDLE'):

                with m.If(self.trigger):
                    m.next = 'SAMPLE'

                    # Grab a sample as our trigger is asserted.
                    m.d.sync += [
                        write_port.en  .eq(1),
                        write_position .eq(0),

                        self.complete  .eq(0),
                    ]

            # SAMPLE: do our sampling
            with m.State('SAMPLE'):

                # Sample until we run out of samples.
                m.d.sync += [
                    write_port.en  .eq(1),
                    write_position .eq(write_position + 1),
                ]

                # If this is the last sample, we're done. Finish up.
                with m.If(write_position + 1 == self.sample_depth):
                    m.next = "IDLE"

                    m.d.sync += [
                        self.complete .eq(1),
                        write_port.en .eq(0)
                    ]


        # Convert our sync domain to the domain requested by the user, if necessary.
        if self.domain != "sync":
            m = DomainRenamer({"sync": self.domain})(m)

        return m


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



class SyncSerialILA(Elaboratable):
    """ Super-simple ILA that reads samples out over a simple unidirectional SPI.
    Create a receiver for this object by calling apollo.ila_receiver_for(<this>).

    This protocol is simple: every time CS goes low, we begin sending out a bit of
    sample on each rising edge. Once a new sample is complete, the next sample begins
    on the next byte boundary.

    Accordingly, sending out two samples of seven bits would look like this:

    ___                                                                ___
   CS |_______________________________________________________________|
          _   _   _   _   _   _   _   _   _   _   _   _   _   _   _   _
   SCK  _| |_| |_| |_| |_| |_| |_| |_| |_| |_| |_| |_| |_| |_| |_| |_|

   SDO <6 ><5 ><4 ><3 ><2 ><1 ><0 ><XX><6 ><5 ><4 ><3 ><2 ><1 ><0 ><XX>
        |---------SAMPLE 0---------|    |---------SAMPLE 1---------|

    I/O port:
        I: trigger                  -- A strobe that determines when we should start sampling.
        O: sampling                 -- Indicates when sampling is in progress.
        O: complete                 -- Indicates when sampling is complete and ready to be read.

        I: sck       -- Serial clock for the SPI lines.
        O: sdo       -- Serial data out for the SPI lines.
        I: cs        -- Chip select for the SPI lines.
    """


    def __init__(self, *, signals, sample_depth, clock_polarity=0, clock_phase=1, cs_idles_high=False, **kwargs):
        """
        Parameters:
            signals            -- An iterable of signals that should be captured by the ILA.
            sample_depth       -- The depth of the desired buffer, in samples.
            domain             -- The clock domain in which the ILA should operate.
            samples_pretrigger -- The number of our samples which should be captured _before_ the trigger.
                                  This also can act like an implicit synchronizer; so asynchronous inputs
                                  are allowed if this number is >= 2.
            clock_polarity     -- Clock polarity for the output SPI transciever. Optional.
            clock_phase        -- Clock phase for the output SPI transciever. Optional.
            cs_idles_high      -- If True, the CS line will be assumed to be asserted when cs=0.
                                  If False or not provided, the CS line will be assumed to be asserted when cs=1
                                  This can be used to share a simple two-device SPI bus, so two internal endpoints
                                  can use the same CS line, with two opposite polarities.
        """

        #
        # I/O port
        #
        self.spi = SPIBus()

        #
        # Init
        #

        self.clock_phase = clock_phase
        self.clock_polarity = clock_polarity

        # Extract the domain from our keyword arguments, and then translate it to syn
        # before we pass it back below. We'll use a DomainRenamer at the boundary to
        # handle non-sync domains.
        self.domain = kwargs.get('domain', 'sync')
        kwargs['domain'] = 'sync'

        # Create our core integrated logic analyzer.
        self.ila = IntegratedLogicAnalyzer(
            signals=signals,
            sample_depth=sample_depth,
            **kwargs)

        # Copy some core parameters from our inner ILA.
        self.signals       = signals
        self.sample_width  = self.ila.sample_width
        self.sample_depth  = self.ila.sample_depth
        self.sample_rate   = self.ila.sample_rate
        self.sample_period = self.ila.sample_period

        # Figure out how many bytes we'll send per sample.
        self.bytes_per_sample = (self.ila.sample_width + 7) // 8
        self.bits_per_word = self.bytes_per_sample * 8

        # Expose our ILA's trigger and status ports directly.
        self.trigger  = self.ila.trigger
        self.sampling = self.ila.sampling
        self.complete = self.ila.complete


    def elaborate(self, platform):
        m  = Module()
        m.submodules.ila = self.ila

        transaction_start = rising_edge_detector(m, self.spi.cs)

        # Connect up our SPI transciever to our public interface.
        interface = SPIDeviceInterface(
            word_size=self.bits_per_word,
            clock_polarity=self.clock_polarity,
            clock_phase=self.clock_phase
        )
        m.submodules.spi = interface
        m.d.comb += [
            interface.spi      .connect(self.spi),

            # Always output the captured sample.
            interface.word_out .eq(self.ila.captured_sample)
        ]

        # Count where we are in the current transmission.
        current_sample_number = Signal(range(0, self.ila.sample_depth))

        # Our first piece of data is latched in when the transaction
        # starts, so we'll move on to sample #1.
        with m.If(self.spi.cs):
            with m.If(transaction_start):
                m.d.sync += current_sample_number.eq(1)

            # From then on, we'll move to the next sample whenever we're finished
            # scanning out a word (and thus our current samples are latched in).
            with m.Elif(interface.word_complete):
                m.d.sync += current_sample_number.eq(current_sample_number + 1)

        # Whenever CS is low, we should be providing the very first sample,
        # so reset our sample counter to 0.
        with m.Else():
            m.d.sync += current_sample_number.eq(0)


        # Ensure our ILA module outputs the right sample.
        m.d.sync += [
            self.ila.captured_sample_number .eq(current_sample_number)
        ]

        return m


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
            datum = data[0:2]
            del data[0:2]

            expected = b"\x0f" + bytes([i])
            self.assertEqual(datum, expected)
            i += 1


class ILAFrontend(metaclass=ABCMeta):
    """ Class that communicates with an ILA module and emits useful output. """

    def __init__(self, ila):
        """
        Parameters:
            ila -- The ILA object to work with.
        """
        self.ila = ila
        self.samples = None


    @abstractmethod
    def _read_samples(self):
        """ Read samples from the target ILA. Should return an iterable of samples. """


    def _parse_sample(self, raw_sample):
        """ Converts a single binary sample to a dictionary of names -> sample values. """

        position = 0
        sample   = {}

        # Split our raw, bits(0) signal into smaller slices, and associate them with their names.
        for signal in self.ila.signals:
            signal_width = len(signal)
            signal_bits  = raw_sample[position : position + signal_width]

            sample[signal.name] = signal_bits

        return sample


    def _parse_samples(self, raw_samples):
        """ Converts raw, binary samples to dictionaries of name -> sample. """
        return (self._parse_sample(sample) for sample in raw_samples)


    def refresh(self):
        """ Fetches the latest set of samples from the target ILA. """
        self.samples = self._parse_samples(self._read_samples())


    def enumerate_samples(self):
        """ Returns an iterator that returns pairs of (timestamp, sample). """

        # If we don't have any samples, fetch samples from the ILA.
        if self.samples is None:
            self.refresh()

        timestamp = 0

        # Iterate over each sample...
        for sample in self.samples:
            yield timestamp, sample

            # ... and advance the timestamp by the relevant interval.
            timestamp += self.ila.sample_period


    def print_samples(self):
        """ Simple method that prints each of our samples; for simple CLI debugging."""

        for timestamp, sample in self.enumerate_samples():
            timestamp_scaled = 1000000 * timestamp
            print(f"{timestamp_scaled:08f}us: {sample}")


    def emit_vcd(self, filename):

        # Select the file-like object we're working with.
        if filename == "-":
            stream = sys.stdout
            close_after = False
        else:
            stream = open(filename, 'w')
            close_after = True

        # Create our basic VCD.
        with VCDWriter(stream, timescale=f"1 ns", date='today') as writer:

            # Create named values for each of our signals.
            signals = {}
            for signal in self.ila.signals:
                signals[signal.name] = writer.register_var('ila', signal.name, 'integer', size=len(signal))

            # Dump the each of our samples into the VCD.
            for timestamp, sample in self.enumerate_samples():
                for signal_name, signal_value in sample.items():
                    writer.change(signals[signal_name], timestamp / 1e-9, signal_value.to_int())



if __name__ == "__main__":
    unittest.main()
