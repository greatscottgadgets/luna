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

from amaranth       import *

from ....test.utils  import LunaSSGatewareTestCase, ss_domain_test_case
from ....utils       import synchronize, rising_edge_detected

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
    def __init__(self, lfps_pattern, ss_clk_frequency=125e6):
        self._pattern              = lfps_pattern
        self._clock_frequency      = ss_clk_frequency

        #
        # I/O port
        #
        self.signaling_detected = Signal() # i
        self.detect             = Signal() # o


    def elaborate(self, platform):
        m = Module()

        # Create an in-domain version of our square-wave-detector signal.
        present = synchronize(m, self.signaling_detected, o_domain="ss")

        # Figure out how large of a counter we're going to need...
        burst_cycles_min    = _ns_to_cycles(self._clock_frequency, self._pattern.burst.t_min)
        burst_cycles_max    = _ns_to_cycles(self._clock_frequency, self._pattern.burst.t_max)

        # If we have a repeat interval, include it in our calculations.
        if self._pattern.repeat is not None:
            repeat_cycles_max   = _ns_to_cycles(self._clock_frequency, self._pattern.repeat.t_max)
            repeat_cycles_min   = _ns_to_cycles(self._clock_frequency, self._pattern.repeat.t_min)
            counter_max         = max(burst_cycles_max, repeat_cycles_max)
        else:
            counter_max         = burst_cycles_max

        # ... and create our counter.
        count = Signal(range(0, counter_max + 1))
        m.d.ss += count.eq(count + 1)

        # Keep track of whether our previous iteration matched; as we're typically in detecting
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
                with m.If(rising_edge_detected(m, present, domain="ss")):
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

                    # If our burst ended within a reasonable span, we can move on.
                    with m.Else():

                        # If we don't have a repeat interval, we're done!
                        if self._pattern.repeat is None:
                            m.d.comb += self.detect.eq(1)
                            m.next = "WAIT_FOR_NEXT_BURST"

                        # Otherwise, we'll need to check the repeat interval, as well.
                        else:
                            m.next = "MEASURE_REPEAT"

            if self._pattern.repeat is not None:

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
        self.start                  = Signal()   # i
        self.done                   = Signal()   # o
        self.length                 = Signal(32) # i

        self.send_lfps_signaling    = Signal()      # o


    def elaborate(self, platform):
        m = Module()

        #
        # Burst generator.
        #
        cycles_left_in_burst = Signal.like(self.length)

        with m.FSM(domain="ss"):

            # IDLE -- we're currently waiting for an LFPS burst to be requested.
            with m.State("IDLE"):
                m.d.comb += self.done.eq(1)
                m.d.ss   += [
                    #period_timer          .eq(0),
                    cycles_left_in_burst  .eq(self.length)
                ]

                with m.If(self.start):
                    m.next = "BURST"

            # BURST -- we've started a burst; and now we'll wait here until the burst is complete.
            with m.State("BURST"):
                m.d.comb += self.send_lfps_signaling  .eq(1)
                m.d.ss += cycles_left_in_burst.eq(cycles_left_in_burst - 1)

                with m.If(cycles_left_in_burst == 0):
                    m.next = "IDLE"

        return m



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
        self.generate               = Signal()      # i
        self.count                  = Signal(16)    # o

        # Transceiver
        self.drive_electrical_idle  = Signal()
        self.send_lfps_signaling    = Signal()


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

                # Once we get one, start a burst.
                with m.If(self.generate):
                    m.d.ss   += [
                        burst_generator.start   .eq(1),
                        burst_generator.length  .eq(full_burst_length),
                        burst_repeat_count      .eq(full_repeat_length),
                    ]
                    m.next = "BURST_AND_WAIT"


            # BURST_AND_WAIT -- we've now triggered a burst; we'll wait until
            # the interval between bursts (the "repeat" interval) before allowing
            # another burst.
            with m.State("BURST_AND_WAIT"):
                m.d.comb += [
                    self.drive_electrical_idle  .eq(1),
                    self.send_lfps_signaling    .eq(burst_generator.send_lfps_signaling)
                ]
                m.d.ss   += [
                    burst_generator.start       .eq(0),
                    burst_repeat_count          .eq(burst_repeat_count - 1)
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
        while (yield dut.drive_electrical_idle):

            # ... and measure how long our burst lasts...
            if (yield dut.send_lfps_signaling):
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

    send_lfps_signaling: Signal(), output
        Held high when our PHY should be generating LFPS square waves.
    lfps_signaling_detected: Signal(), input
        Should be asserted when our PHY is detecting LFPS square waves.

    send_lfps_polling: Signal(), input
        Strobe. When asserted, begins an LFPS burst.
    lfps_polling_detected: Signal(), output
        Strobes high when Polling LFPS is detected.
    lfps_polling_detected: Signal(), output
        Strobes high when Reset LFPS is detected.

    tx_count: Signal(16), output
        Indicates how many LFPS bursts we've sent since the last request.
    """

    def __init__(self, ss_clk_freq=125e6, lfps_clk_freq=_DEFAULT_LFPS_FREQ):
        self._clock_frequency      = ss_clk_freq
        self._lpfs_frequency       = lfps_clk_freq

        #
        # I/O port
        #
        self.send_lfps_signaling     = Signal()
        self.lfps_signaling_detected = Signal()

        # LFPS burst generation
        self.send_lfps_polling       = Signal()

        # LFPS burst reception
        self.lfps_polling_detected   = Signal()
        self.lfps_reset_detected     = Signal()

        self.tx_count                = Signal(16)


    def elaborate(self, platform):
        m = Module()

        #
        # LFPS Receiver.
        #
        polling_checker = LFPSDetector(_PollingLFPS, self._clock_frequency)
        m.submodules += polling_checker
        m.d.comb += [
            polling_checker.signaling_detected  .eq(self.lfps_signaling_detected),
            self.lfps_polling_detected          .eq(polling_checker.detect)
        ]

        reset_checker = LFPSDetector(_ResetLFPS, self._clock_frequency)
        m.submodules += reset_checker
        m.d.comb += [
            reset_checker.signaling_detected  .eq(self.lfps_signaling_detected),
            self.lfps_reset_detected          .eq(reset_checker.detect)
        ]


        #
        # LFPS Transmitter(s).
        #
        polling_generator = LFPSGenerator(_PollingLFPS, self._clock_frequency, self._lpfs_frequency)
        m.submodules += polling_generator

        m.d.comb += [
            polling_generator.generate .eq(self.send_lfps_polling),

            # Drive our outputs with the outputs generated by our generator...
            self.send_lfps_signaling    .eq(polling_generator.send_lfps_signaling),
            self.tx_count               .eq(polling_generator.count),
        ]

        return m


if __name__ == "__main__":
    unittest.main()
