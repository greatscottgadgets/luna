#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
#
# SPDX-License-Identifier: BSD-3-Clause
""" Generating and recognizing LFPS square wave patterns.

SerDes blocks differ in their out-of-band signaling capabilities. Some are capable of detecting
and generating LFPS signaling on their own; others only make it possible to access the high-speed
I/O buffers directly through fabric. This gateware can detect patterns that fit LFPS requriements
given only a bare input buffer, or vice versa.
"""

from math import ceil
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer


__all__ = ['LFPSSquareWaveDetector', 'LFPSSquareWaveGenerator']


# From [USB3.2: Table 6-29]; the maximum and minimum
_LFPS_PERIOD_MIN =  20e-9 # seconds
_LFPS_PERIOD_MAX = 100e-9



class LFPSSquareWaveDetector(Elaboratable):
    """ Detector that identifies LFPS square-wave patterns.

    Operates in the ``pipe`` domain.

    Attributes
    ----------
    rx_gpio: Signal(), input
        The current state of the Rx lines, as retrieved by our SerDes.
    present: Signal(), output
        High whenever we detect an LFPS toggling.
    """

    def __init__(self, pipe_clock_frequency=250e6):

        # Compute the minimum and maximum cycles we're allowed to see.
        # Our multipliers allow for up to a 10% devication in duty cycle.
        self._half_cycle_min = ceil(pipe_clock_frequency * (_LFPS_PERIOD_MIN / 2) * 0.8) - 1
        self._half_cycle_max = ceil(pipe_clock_frequency * (_LFPS_PERIOD_MAX / 2) * 1.2) + 1
        assert self._half_cycle_min >= 1


        #
        # I/O ports
        #
        self.rx_gpio = Signal() # i
        self.present = Signal() # o


    def elaborate(self, platform):
        m = Module()

        # Synchronize the GPIO to our clock domain.
        rx_gpio = Signal()
        m.submodules += FFSynchronizer(self.rx_gpio, rx_gpio, o_domain="pipe")

        # Our mechanism is simple: we measure the length of any periods of consecutive highs and lows
        # we see, and then check to see when they're both in acceptable ranges. Theoretically, we should
        # also check the duty cycle, but as of now, that doesn't seem necessary. [USB3.2: Table 6-29]

        # Keep track of the GPIO's value a cycle ago, so we can easily detect rising and falling edges.
        last_gpio = Signal()
        m.d.pipe += last_gpio.eq(rx_gpio)

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
        with m.If(rx_gpio):

            # Count only when we've reached a value lower than the timer's max,
            # so we saturate once we're outside the acceptable range.
            with m.If(current_time_high != timer_max):
                m.d.pipe += current_time_high.eq(current_time_high + 1)

            # If we've saturated our count, immediately set the total time
            # to the saturation value. This prevents false detections after long
            # strings of constant value.
            with m.Else():
                m.d.pipe += total_time_high.eq(timer_max)


        # If we were still counting last cycle, we'll latch our observed time
        # high before our timer gets cleared. This value represents our total
        # time high, and thus the value we'll use for comparison.
        with m.Elif(last_gpio):
            m.d.pipe += [
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
        with m.If(~rx_gpio):

            # Count only when we've reached a value lower than the timer's max,
            # so we saturate once we're outside the acceptable range.
            with m.If(current_time_low != timer_max):
                m.d.pipe += current_time_low.eq(current_time_low + 1)

            # If we've saturated our count, immediately set the total time
            # to the saturation value. This prevents false detections after long
            # strings of constant value.
            with m.Else():
                m.d.pipe += total_time_low.eq(timer_max)

        # If we were still counting last cycle, we'll latch our observed time
        # low before our timer gets cleared. This value represents our total
        # time high, and thus the value we'll use for comparison.
        with m.Elif(~last_gpio):
            m.d.pipe += [
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



class LFPSSquareWaveGenerator(Elaboratable):
    """Generator that outputs LFPS square-wave patterns.
    """
    def __init__(self, lfps_frequency, pipe_clock_frequency):

        # Compute the cycles in one half-period, and make sure the final period is within the spec.
        self._half_cycle = ceil(pipe_clock_frequency / (2 * lfps_frequency))
        assert _LFPS_PERIOD_MIN <= (2 * self._half_cycle) / pipe_clock_frequency <= _LFPS_PERIOD_MAX


        #
        # I/O ports
        #
        self.generate   = Signal() # i

        self.tx_gpio_en = Signal() # o
        self.tx_gpio    = Signal() # o


    def elaborate(self, platform):
        m = Module()

        #
        # LFPS square-wave generator.
        #
        period_timer = Signal(range(self._half_cycle))
        square_wave  = Signal()

        m.d.pipe += period_timer.eq(period_timer + 1)
        with m.If(period_timer + 1 == self._half_cycle):
            m.d.pipe += period_timer.eq(0)
            m.d.pipe += square_wave.eq(~square_wave)

        with m.If(self.generate):
            m.d.comb += [
                self.tx_gpio_en.eq(1),
                self.tx_gpio   .eq(square_wave),
            ]

        return m
