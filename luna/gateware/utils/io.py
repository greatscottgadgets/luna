# amaranth: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Helpers for I/O interfacing. """

import unittest
from unittest import TestCase

from amaranth import Record, Instance, Module, Signal, Cat
from amaranth.hdl.rec import DIR_FANIN, DIR_FANOUT


# FIXME: move this out of here and into an ECP5-specific set of functionality
def delay(m, signal, interval, *, out=None):
    """ Creates a delayed copy of a given I/O signal.

    Currently only works at the FPGA's I/O boundary, and only on ECP5s.

    Parameters:
        signal -- The signal to be delayed. Must be either an I/O
                  signal connected directly to a platform resource.
        delay  -- Delay, in arbitrary units. These units will vary
                  from unit to unit, but seem to be around 300ps on
                  most ECP5 FPGAs. On ECP5s, maxes out at 127.
        out    -- The signal to received the delayed signal; or
                  None ot have a signal created for you.

    Returns:
        delayed -- The delayed signal. Will be equivalent to 'out'
                   if provided; or a new signal otherwise.
    """

    # If we're not being passed our output signal, create one.
    if out is None:
        out = Signal.like(signal)

    # If we have more than one signal, call this function on each
    # of the subsignals.
    if len(signal) > 1:

        # If we have a vector of signals, but a integer delay,
        # convert that integer to a vector of same-valued delays.
        if isinstance(interval, int):
            interval = [interval] * len(signal)

        return Cat(delay(m, s, d, out=o) for s, d, o in zip(signal, interval, out))

    #
    # Base case: create a delayed version of the relevant signal.
    #
    m.submodules += Instance("DELAYG",
        i_A=signal,
        o_Z=out,
        p_DEL_VALUE=interval
    )

    return out
