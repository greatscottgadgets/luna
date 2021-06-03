#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based in part on ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Low-frequency periodic signaling gateware.

LFPS is the first signaling to happen during the initialization of the USB3.0 link.

LFPS allows partners to exchange Out Of Band (OOB) controls/commands and consists of bursts where
a "slow" clock is generated (between 10M-50MHz) for a specific duration and with a specific repeat
period. After the burst, the transceiver is put in electrical idle mode (same electrical level on
P/N pairs while in nominal mode P/N pairs always have an opposite level):

Transceiver level/mode: _=0, -=1 x=electrical idle
|-_-_-_-xxxxxxxxxxxxxxxxxxxx|-_-_-_-xxxxxxxxxxxxxxxxxxxx|...
|<burst>                    |<burst>                    |...
|<-----repeat period------->|<-----repeat period------->|...

A LFPS pattern is identified by a burst duration and repeat period.

To be able generate and receive LFPS, a transceiver needs to be able put its TX in electrical idle
and to detect RX electrical idle.
"""

import unittest
from math import ceil

from nmigen         import *
from nmigen.lib.cdc import FFSynchronizer
from nmigen.hdl.ast import Rose, Past

from ...test.utils  import LunaSSGatewareTestCase, ss_domain_test_case
from ...utils.cdc   import synchronize

__all__ = ['LFPSTransceiver']

#
# LPFS timing "constants", and collection classes that represent them.
#

class LFPSTiming:
    """LPFS timings with typical, minimum and maximum timing values."""

    def __init__(self, t_typ=None, t_min=None, t_max=None):
        self.t_typ = t_typ
        self.t_min = t_min
        self.t_max = t_max
        assert t_min is not None
        assert t_max is not None

        self.range = (t_min, t_max)


class LFPS:
    """LPFS patterns with burst and repeat timings."""

    def __init__(self, burst, repeat=None, cycles=None):
        self.burst  = burst
        self.repeat = repeat
        self.cycles = None


def _ns_to_cycles(clk_freq, t):
    return ceil(t*clk_freq)


_DEFAULT_LFPS_FREQ = 30e6

_LFPS_CLK_FREQ_MIN = 1/100e-9
_LFPS_CLK_FREQ_MAX = 1/20e-9


# Our actual pattern constants; as specified by the USB3 specification.
# [USB 3.2r1: Table 6-30]
_PollingLFPSBurst  = LFPSTiming(t_typ=1.0e-6,  t_min=0.6e-6, t_max=1.4e-6)
_PollingLFPSRepeat = LFPSTiming(t_typ=10.0e-6, t_min=6.0e-6, t_max=14.0e-6)
_PollingLFPS       = LFPS(burst=_PollingLFPSBurst, repeat=_PollingLFPSRepeat)

_ResetLFPSBurst    = LFPSTiming(t_typ=100.0e-3, t_min=80.0e-3,  t_max=120.0e-3)
_ResetLFPS         = LFPS(burst=_ResetLFPSBurst)


class LFPSSquareWaveDetector(Elaboratable):
    """ Detector that identifies LFPS square-wave patterns.

    Operates in the ``fast`` domain.

    Attributes
    ----------
    rx_gpio: Signal(), input
        The current state of the Rx lines, as retrieved by our SerDes.
    present: Signal(), output
        High whenever we detect an LFPS toggling.
    """

    # From [USB3.2: Table 6-29]; the maximum and minimum
    PERIOD_MIN           =  20e-9
    PERIOD_MAX           = 100e-9

    def __init__(self, fast_clock_frequency=250e6):

        # Compute the minimum and maximum cycles we're allowed to see.
        # Our multipliers allow for up to a 10% devication in duty cycle.
        self._half_cycle_min = _ns_to_cycles(fast_clock_frequency, (self.PERIOD_MIN / 2) * 0.8) - 1
        self._half_cycle_max = _ns_to_cycles(fast_clock_frequency, (self.PERIOD_MAX / 2) * 1.2) + 1
        assert(self._half_cycle_min >= 1)


        #
        # I/O port
        #
        self.rx_gpio = Signal()
        self.present = Signal()


    def elaborate(self, platform):
        m = Module()

        # Our mechanism is simple: we measure the length of any periods of consecutive highs and lows
        # we see, and then check to see when they're both in acceptable ranges. Theoretically, we should
        # also check the duty cycle, but as of now, that doesn't seem necessary. [USB3.2: Table 6-29]

        # Keep track of the GPIO's value a cycle ago, so we can easily detect rising and falling edges.
        last_gpio = Signal()
        m.d.fast += last_gpio.eq(self.rx_gpio)

        # We'll allow each timer to go one cycle past our half-cycle-max, so it can saturate at an unacceptable
        # level, and mark the ranges as invalid.
        timer_max = self._half_cycle_max + 1

        #
        # Time-high detection.
        #

        # Keep track of our current/total time high.
        current_time_high = Signal(range(0, timer_max + 1))
        total_time_high   = Signal.like(current_time_high)

        # If our GPIO is high, count it.
        with m.If(self.rx_gpio):

            # Count only when we've reached a value lower than the timer's max,
            # so we saturate once we're outside the acceptable range.
            with m.If(current_time_high != timer_max):
                m.d.fast += current_time_high.eq(current_time_high + 1)

            # If we've saturated our count, immediately set the total time
            # to the saturation value. This prevents false detections after long
            # strings of constant value.
            with m.Else():
                m.d.fast += total_time_high.eq(timer_max)


        # If we were still counting last cycle, we'll latch our observed time
        # high before our timer gets cleared. This value represents our total
        # time high, and thus the value we'll use for comparison.
        with m.Elif(last_gpio):

                m.d.fast += [
                    total_time_high    .eq(current_time_high),
                    current_time_high  .eq(0)
                ]


        #
        # Time-low detection.
        #

        # Keep track of our current/total time low.
        current_time_low = Signal(range(0, timer_max + 1))
        total_time_low   = Signal.like(current_time_low)

        # If our GPIO is low, count it.
        with m.If(~self.rx_gpio):

            # Count only when we've reached a value lower than the timer's max,
            # so we saturate once we're outside the acceptable range.
            with m.If(current_time_low != timer_max):
                m.d.fast += current_time_low.eq(current_time_low + 1)

            # If we've saturated our count, immediately set the total time
            # to the saturation value. This prevents false detections after long
            # strings of constant value.
            with m.Else():
                m.d.fast += total_time_low.eq(timer_max)

        # If we were still counting last cycle, we'll latch our observed time
        # low before our timer gets cleared. This value represents our total
        # time high, and thus the value we'll use for comparison.
        with m.Elif(~last_gpio):
            m.d.fast += [
                total_time_low    .eq(current_time_low),
                current_time_low  .eq(0)
            ]


        #
        # Final detection.
        #

        # Whenever both our time high and time low are in range, we have a valid period.
        time_high_valid = ((total_time_high >= self._half_cycle_min) & (total_time_high <= self._half_cycle_max))
        time_low_valid  = ((total_time_low  >= self._half_cycle_min) & (total_time_low  <= self._half_cycle_max))
        m.d.comb += self.present.eq(time_high_valid & time_low_valid)

        return m



#
# Core LFPS gateware.
#
class LFPSDetector(Elaboratable):
    """ LFPS signaling detector; detects LFPS signaling in particular patterns.

    Attributes
    ----------
    rx_gpio: Signal(), input
        The current state of the Rx lines, as retrieved by our SerDes.
    detect: Signal(), output
        Strobes high when a valid LFPS burst is detected.

    """
    def __init__(self, lfps_pattern, ss_clk_frequency=125e6, fast_clk_frequency=250e6):
        self._pattern              = lfps_pattern
        self._clock_frequency      = ss_clk_frequency
        self._fast_clock_frequency = fast_clk_frequency

        #
        # I/O port
        #
        self.signaling_detected = Signal() # i
        self.detect             = Signal() # o


    def elaborate(self, platform):
        m = Module()

        # Create an in-domain version of our square-wave-detector signal.
        present = synchronize(m, self.signaling_detected)

        # Figure out how large of a counter we're going to need...
        burst_cycles_min    = _ns_to_cycles(self._clock_frequency, self._pattern.burst.t_min)
        repeat_cycles_min   = _ns_to_cycles(self._clock_frequency, self._pattern.repeat.t_min)
        burst_cycles_max    = _ns_to_cycles(self._clock_frequency, self._pattern.burst.t_max)
        repeat_cycles_max   = _ns_to_cycles(self._clock_frequency, self._pattern.repeat.t_max)
        counter_max         = max(burst_cycles_max, repeat_cycles_max)

        # ... and create our counter.
        count = Signal(range(0, counter_max + 1))
        m.d.ss += count.eq(count + 1)

        # Keep track of whether our previous iteration matched; as we're interested in detecting
        # sequences of two correct LFPS cycles in a row.
        last_iteration_matched = Signal()

        #
        # Detector state machine.
        #
        with m.FSM(domain="ss"):

            # WAIT_FOR_NEXT_BURST -- we're not currently in a measurement; but are waiting for a
            # burst to begin, so we can perform a full measurement.
            with m.State("WAIT_FOR_NEXT_BURST"):
                m.d.ss += last_iteration_matched.eq(0)

                # If we've just seen the start of a burst, start measuring it.
                with m.If(Rose(present)):
                    m.d.ss += count.eq(1),
                    m.next = "MEASURE_BURST"

            # MEASURE_BURST -- we're seeing something we believe to be a burst; and measuring its length.
            with m.State("MEASURE_BURST"):

                # Failing case: if our counter has gone longer than our maximum burst time, this isn't
                # a relevant burst. We'll wait for the next one.
                with m.If(count == burst_cycles_max):
                    m.next = 'WAIT_FOR_NEXT_BURST'

                # Once our burst is over, we'll need to decide if the burst matches our pattern.
                with m.If(~present):

                    # Failing case: if our burst is over, but we've not yet reached our minimum burst time,
                    # then this isn't a relevant burst. We'll wait for the next one.
                    with m.If(count < burst_cycles_min):
                        m.next = 'WAIT_FOR_NEXT_BURST'

                    # If our burst ended within a reasonable span, move on to measuring the spacing between
                    # bursts ("repeat interval").
                    with m.Else():
                        m.next = "MEASURE_REPEAT"


            # MEASURE_REPEAT -- we've just finished seeing a burst; and now we're measuring the gap between
            # successive bursts, which the USB specification calls the "repeat interval". [USB3.2r1: Fig 6-32]
            with m.State("MEASURE_REPEAT"):

                # Failing case: if our counter has gone longer than our maximum burst time, this isn't
                # a relevant burst. We'll wait for the next one.
                with m.If(count == repeat_cycles_max):
                    m.next = 'WAIT_FOR_NEXT_BURST'

                # Once we see another potential burst, we'll start our detection back from the top.
                with m.If(present):
                    m.d.ss += count.eq(1)
                    m.next = 'MEASURE_BURST'

                    # If this lasted for a reasonable repeat interval, we've seen a correct burst!
                    with m.If(count >= repeat_cycles_min):

                        # Mark this as a correct iteration, and if the previous iteration was also
                        # a correct one, indicate that we've detected our output.
                        m.d.ss   += last_iteration_matched.eq(1)
                        m.d.comb += self.detect.eq(last_iteration_matched)

                    with m.Else():
                        m.d.ss   += last_iteration_matched.eq(0)

        return m



class LFPSBurstGenerator(Elaboratable):
    """LFPS Burst Generator

    Generate a LFPS burst of configurable length on the TX lane. The LFPS clock is generated by
    sending an alternating ones/zeroes data pattern on the parallel interface of the transceiver.
    """
    def __init__(self, sys_clk_freq, lfps_clk_freq):
        self._clock_frequency = sys_clk_freq
        self._lfps_clk_freq   = lfps_clk_freq

        # Validate that our frequency is within the allowed bounds.
        assert lfps_clk_freq >= _LFPS_CLK_FREQ_MIN
        assert lfps_clk_freq <= _LFPS_CLK_FREQ_MAX

        #
        # I/O ports
        #
        self.start      = Signal()   # i
        self.done       = Signal()   # o
        self.length     = Signal(32) # i


        self.tx_idle    = Signal(reset=1) # o
        self.tx_gpio    = Signal()      # o


    def elaborate(self, platform):
        m = Module()

        #
        # LFPS square-wave generator.
        #
        timer_max = ceil(self._clock_frequency/(2*self._lfps_clk_freq)) - 1

        square_wave  = Signal()
        period_timer = Signal(range(0, timer_max + 1))

        with m.If(period_timer == 0):
            m.d.ss += [
                square_wave    .eq(~square_wave),
                period_timer   .eq(timer_max - 1)
            ]
        with m.Else():
            m.d.ss += period_timer.eq(period_timer - 1)


        #
        # Burst generator.
        #
        cycles_left_in_burst = Signal.like(self.length)

        with m.FSM(domain="ss"):

            # IDLE -- we're currently waiting for an LFPS burst to be requested.
            with m.State("IDLE"):
                m.d.comb += self.done.eq(1)
                m.d.ss   += [
                    period_timer          .eq(0),
                    cycles_left_in_burst  .eq(self.length)
                ]

                with m.If(self.start):
                    m.next = "BURST"

            # BURST -- we've started a burst; and now we'll wait here until the burst is complete.
            with m.State("BURST"):
                m.d.comb += [
                    self.tx_idle     .eq(0),
                    self.tx_gpio     .eq(square_wave),
                ]
                m.d.ss += cycles_left_in_burst.eq(cycles_left_in_burst - 1)

                with m.If(cycles_left_in_burst == 0):
                    m.next = "IDLE"

        return m

class LFPSBurstGeneratorTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = LFPSBurstGenerator
    FRAGMENT_ARGUMENTS = dict(
        sys_clk_freq  = 125e6,
        lfps_clk_freq = _DEFAULT_LFPS_FREQ
    )

    def stimulus(self):
        """ Test stimulus for our burst clock generator. """
        dut = self.dut

        # Create eight bursts of 256 pulses.
        for _ in range(8):
            yield dut.length.eq(256)
            yield dut.start.eq(1)
            yield
            yield dut.start.eq(0)
            while not (yield dut.done):
                yield
            for __ in range(256):
                yield


    def setUp(self):
        # Hook our setup function, and add in our stimulus.
        super().setUp()
        self.sim.add_sync_process(self.stimulus, domain="ss")


    @ss_domain_test_case
    def test_lpfs_burst_duty_cycle(self):
        dut = self.dut

        transitions  = 0
        ones_ticks   = 0
        zeroes_ticks = 0
        tx_gpio      = 0

        # Wait a couple of cycles for our stimulus to set up our burst.
        yield from self.advance_cycles(2)

        # Wait for a burst cycle...
        while not (yield dut.done):

            # While we're bursting...
            if not (yield dut.tx_idle):

                # ... measure how many clock transitions we see...
                if (yield dut.tx_gpio != tx_gpio):
                    transitions += 1

                # ... as well as what percentage of the time the clock is 1 vs 0.
                if (yield dut.tx_gpio != 0):
                    ones_ticks   += 1
                else:
                    zeroes_ticks += 1

                tx_gpio = (yield dut.tx_gpio)
            yield

        # Figure out the total length that we've run for.
        total_ticks = ones_ticks + zeroes_ticks

        # We should measure a duty cycle that's within 10% of 50%...
        self.assertLess(abs(ones_ticks   / (total_ticks) - 50e-2), 10e-2)
        self.assertLess(abs(zeroes_ticks / (total_ticks) - 50e-2), 10e-2)

        # ... and our total length should be within 10% of nominal.
        expected_cycles = self.SS_CLOCK_FREQUENCY/_DEFAULT_LFPS_FREQ
        computed_cycles = 2*total_ticks/transitions
        self.assertLess(abs(expected_cycles/computed_cycles - 1.0), 10e-2)


class LFPSGenerator(Elaboratable):
    """LFPS Generator

    Generate a specific LFPS pattern on the TX lane. This module handles LFPS clock generation, LFPS
    burst generation and repetition.
    """
    def __init__(self, lfps_pattern, sys_clk_freq, lfps_clk_freq):
        self._pattern         = lfps_pattern
        self._clock_frequency = sys_clk_freq
        self._lpfs_frequency  = lfps_clk_freq

        #
        # I/O port
        #

        # Control
        self.generate = Signal()      # i
        self.count    = Signal(16)    # o

        # Transceiver
        self.tx_idle    = Signal() # o
        self.tx_gpio    = Signal() # o

        # Diagnostic
        self.busy       = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # LFPS burst generator.
        #
        m.submodules.burst_gen = burst_generator = LFPSBurstGenerator(
            sys_clk_freq=self._clock_frequency,
            lfps_clk_freq=self._lpfs_frequency
        )

        #
        # Controller
        #
        burst_repeat_count = Signal(32)
        full_burst_length  = int(self._clock_frequency*self._pattern.burst.t_typ)
        full_repeat_length = int(self._clock_frequency*self._pattern.repeat.t_typ)

        with m.FSM(domain="ss"):

            # IDLE -- wait for an LFPS burst request.
            with m.State("IDLE"):
                m.d.comb += self.tx_idle  .eq(0)
                m.d.ss   += self.count    .eq(0)

                # Once we get one, start a burst.
                with m.If(self.generate):
                    m.d.comb += self.tx_idle.eq(1)
                    m.d.ss   += [
                        burst_generator.start   .eq(1),
                        burst_generator.length  .eq(full_burst_length),
                        burst_repeat_count      .eq(full_repeat_length),
                    ]
                    m.next = "BURST_AND_WAIT"


            # BURST_AND_WAIT -- we've now triggered a burst; we'll wait until
            # the interval between bursts (the "repeat" interal) before allowing
            # another burst.
            with m.State("BURST_AND_WAIT"):
                m.d.comb += [
                    self.busy              .eq(1),
                    self.tx_idle           .eq(burst_generator.tx_idle),
                    self.tx_gpio           .eq(burst_generator.tx_gpio)
                ]
                m.d.ss   += [
                    burst_generator.start  .eq(0),
                    burst_repeat_count     .eq(burst_repeat_count - 1)
                ]

                # Once we've waited the repeat interval, return to ready.
                with m.If(burst_repeat_count == 0):
                    m.d.ss += self.count.eq(self.count + 1)
                    m.next = "IDLE"

        return m


class LFPSGeneratorTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = LFPSGenerator
    FRAGMENT_ARGUMENTS  = dict(
        lfps_pattern = _PollingLFPS,
        sys_clk_freq = 125e6,
        lfps_clk_freq= _DEFAULT_LFPS_FREQ
    )

    @ss_domain_test_case
    def test_polling_lfps_sequence(self):
        dut = self.dut

        burst_length=int(self.SS_CLOCK_FREQUENCY * _PollingLFPSBurst.t_typ)
        burst_repeat=int(self.SS_CLOCK_FREQUENCY * _PollingLFPSRepeat.t_typ)

        # Trigger a burst...
        yield dut.generate.eq(1)
        yield
        yield

        # Wait for a whole burst-repeat cycle...
        burst_ticks = 0
        total_ticks = 0
        while (yield dut.busy):

            # ... and measure how long our burst lasts...
            if not (yield dut.tx_idle):
                burst_ticks += 1

            # ... as well as the length of our whole interval.
            total_ticks += 1
            yield

        # Our observed burst length should be within 10% of our specification...
        self.assertLess(abs(burst_ticks)/burst_length - 1.0, 10e-2)

        # ... as should our observed total length between bursts.
        self.assertLess(abs(total_ticks)/burst_repeat - 1.0, 10e-2)



class LFPSTransceiver(Elaboratable):
    """ Low-Frequency Periodic Signaling (LFPS) Transciever.

    Transmits and receives the LPFS required for a USB3.0 link.

    Attributes
    ----------

    rx_polling: Signal(), output
        Strobes high when Polling LFPS is detected.

    tx_idle: Signal(), input
        When asserted, indicates that the output lines should be held in electrical idle.
    tx_polling: Signal(), input
        Strobe. When asserted, begins an LFPS burst.

    tx_count: Signal(16), output
        [FIXME Document better] -> Indicates the current position in the LFPS transmission.
    """

    def __init__(self, ss_clk_freq=125e6, fast_clock_frequency=250e6, lfps_clk_freq=_DEFAULT_LFPS_FREQ):
        self._clock_frequency      = ss_clk_freq
        self._fast_clock_frequency = fast_clock_frequency
        self._lpfs_frequency       = lfps_clk_freq

        #
        # I/O port
        #
        self.drive_tx_gpio           = Signal()
        self.tx_gpio                 = Signal()
        self.lfps_signaling_detected = Signal()

        self.rx_polling              = Signal()
        self.tx_idle                 = Signal()
        self.tx_polling              = Signal()
        self.tx_count                = Signal(16)


    def elaborate(self, platform):
        m = Module()

        #
        # LFPS Receiver.
        #
        polling_checker = LFPSDetector(_PollingLFPS, self._clock_frequency, self._fast_clock_frequency)
        m.submodules += polling_checker
        m.d.comb += [
            polling_checker.signaling_detected  .eq(self.lfps_signaling_detected),
            self.rx_polling                     .eq(polling_checker.detect)
        ]

        #
        # LFPS Transmitter(s).
        #
        polling_generator = LFPSGenerator(_PollingLFPS, self._clock_frequency, self._lpfs_frequency)
        m.submodules += polling_generator

        m.d.comb += [
            polling_generator.generate .eq(self.tx_polling),

            # Drive our outputs with the outputs generated by our generator...
            self.tx_idle               .eq(polling_generator.tx_idle),
            self.tx_gpio               .eq(polling_generator.tx_gpio),
            self.tx_count              .eq(polling_generator.count),

            # ... and take control of the Tx GPIO whenever we're driving our polling pattern.
            self.drive_tx_gpio         .eq(self.tx_polling & ~self.tx_idle)
        ]

        return m


if __name__ == "__main__":
    unittest.main()
