#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Logical idle detection / polling gateware. """

from amaranth         import *
from amaranth.hdl.ast import Past

from ...stream        import USBRawSuperSpeedStream

class IdleHandshakeHandler(Elaboratable):
    """ Unit that performs the USB3 idle handshake.

    The Idle Handshake occurs after link training; and is the first step of
    post-training link initialization.

    Attributes
    ----------
    enable: Signal(), input
        Indicates that the idle handshake has started; which is used to create the
        :attr:``idle_handshake_complete`` signal. It should be asserted once we enter
        Polling.Idle.

    sink: USBRawSuperSpeedStream(), input stream
        Raw post-descrambling stream from the physical layer.

    idle_detected: Signal(), output
        Asserted when the last eight word-aligned symbols detected have been logical
        idle; identifying a completed idle handshake.
    idle_handshake_complete: Signal(), output
        Asserted when we've seen IDLE at least once, and we've been enabled for at least
        16 cycles, as required by the USB3 Idle Handshake [USB3.2r1: 7.5.4.10].
    """

    # We need to send 16B of idle during our handshake. Since we're sending 4B per cycle,
    # that's a total of four cycles.
    RX_CYCLES_REQUIRED = 4

    def __init__(self):

        #
        # I/O port
        #
        self.sink                    = USBRawSuperSpeedStream()

        self.enable                  = Signal()
        self.idle_detected           = Signal()
        self.idle_handshake_complete = Signal()


    def elaborate(self, platform):
        m = Module()

        data_word = self.sink.data
        ctrl_word = self.sink.ctrl

        # Capture the previous data word; so we have a record of eight consecutive signals.
        last_word = Past(self.sink.data)
        last_ctrl = Past(self.sink.ctrl)

        # Logical idle descrambles to the raw data value zero; so we only need to validate that
        # the last and current words are both zeroes.
        last_word_was_idle   = (last_word == 0) & (last_ctrl == 0)
        current_word_is_idle = (data_word == 0) & (ctrl_word == 0)
        m.d.comb += [
            self.idle_detected  .eq(last_word_was_idle & current_word_is_idle)
        ]

        #
        # Handshake condition detector.
        #
        seen_idle      = Signal()
        enable_counter = Signal(range(self.RX_CYCLES_REQUIRED + 1))

        with m.If(self.enable):

            # Keep track of how many consecutive cycles we're enabled for; as we must
            # send logical idle for at least 16B in order to complete the Idle handshake.
            with m.If(enable_counter < self.RX_CYCLES_REQUIRED):
                m.d.ss += enable_counter.eq(enable_counter + 1)

            # Keep track of whether we've ever seen eight consecutive cycles of idle.
            with m.If(self.idle_detected):
                m.d.ss += seen_idle.eq(1)

            # Our handshake is complete once we've sent logical idle for at least 16 bytes,
            # and we've seen at least eight byte
            send_condition_met = enable_counter == self.RX_CYCLES_REQUIRED
            m.d.comb += self.idle_handshake_complete.eq(seen_idle & send_condition_met)


        # When we're not idle, clear all of our state.
        with m.Else():
            m.d.ss += [
                enable_counter  .eq(0),
                seen_idle       .eq(0)
            ]

        return m
