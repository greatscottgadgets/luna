#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Logical idle detection / polling gateware. """

from nmigen         import *
from nmigen.hdl.ast import Past

from ...stream      import USBRawSuperSpeedStream

class IdleHandshakeHandler(Elaboratable):
    """ Unit that performs the USB3 idle handshake.

    The Idle Handshake occurs after link training; and is the first step of
    post-training link initialization.

    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input stream
        Raw post-descrambling stream from the physical layer.

    idle_detected: Signal(), output
        Asserted when the last eight word-aligned symbols detected have been logical
        idle; identifying a completed idle handshake.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.sink          = USBRawSuperSpeedStream()

        self.idle_detected = Signal()


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

        return m
