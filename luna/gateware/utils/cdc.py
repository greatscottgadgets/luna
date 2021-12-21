# amaranth: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Helpers for clock domain crossings. """

import unittest
import warnings

from unittest       import TestCase
from amaranth       import Record, Module, Signal
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.io  import Pin
from amaranth.hdl.rec import DIR_FANIN, DIR_FANOUT

from ..test         import LunaGatewareTestCase, sync_test_case

def synchronize(m, signal, *, output=None, o_domain='sync', stages=2):
    """ Convenience function. Synchronizes a signal, or equivalent collection.

    Parameters:
        input   -- The signal to be synchronized.
        output  -- The signal to output the result of the synchronization
                   to, or None to have one created for you.
        domain  -- The name of the domain to be synchronized to.
        stages  -- The depth (in FFs) of the synchronization chain.
                   Longer incurs more delay. Must be >= 2 to avoid metastability.

    Returns:
        record  -- The post-synchronization signal. Will be equivalent to the
                   `output` record if provided, or a new, created signal otherwise.
    """

    # Quick function to create a synchronizer with our domain and stages.
    def create_synchronizer(signal, output):
        return FFSynchronizer(signal, output, o_domain=o_domain, stages=stages)

    if output is None:
        if isinstance(signal, Signal):
            output = Signal.like(signal)
        else:
            output = Record.like(signal)

    # If the object knows how to synchronize itself, let it.
    if hasattr(signal, '_synchronize_'):
        signal._synchronize_(m, output, o_domain=o_domain, stages=stages)
        return output

    # Trivial case: if this element doesn't have a layout,
    # we can just synchronize it directly.
    if not hasattr(signal, 'layout'):
        m.submodules += create_synchronizer(signal, output)
        return output

    # Otherwise, we'll need to make sure we only synchronize
    # elements with non-output directions.
    for name, layout, direction in signal.layout:

        # If this is a record itself, we'll need to recurse.
        if isinstance(signal[name], (Record, Pin)):
            synchronize(m, signal[name], output=output[name],
                    o_domain=o_domain, stages=stages)
            continue

        # Skip any output elements, as they're already
        # in our clock domain, and we don't want to drive them.
        if (direction == DIR_FANOUT) or (hasattr(signal[name], 'o') and ~hasattr(signal[name], 'i')):
            m.d.comb += signal[name].eq(output[name])
            continue

        m.submodules += create_synchronizer(signal[name], output[name])

    return output


class SynchronizedTest(TestCase):

    def test_signal(self):
        m = Module()
        synchronize(m, Signal())

    def test_directional_record(self):
        m = Module()

        record = Record([
            ('sig_in',  1, DIR_FANIN),
            ('sig_out', 1, DIR_FANOUT)
        ])
        synchronize(m, record)

    def test_nested_record(self):
        m = Module()

        record = Record([
            ('sig_in',  1, DIR_FANIN),
            ('sig_out', 1, DIR_FANOUT),
            ('nested', [
                ('subsig_in',  1, DIR_FANIN),
                ('subsig_out', 1, DIR_FANOUT),
            ])
        ])
        synchronize(m, record)


def stretch_strobe_signal(m, strobe, *, to_cycles, output=None, domain=None, allow_delay=False):
    """ Stretches a given strobe to the given number of cycles.

    Parameters:
        strobe    -- The strobe signal to stretch.
        to_cycles -- The number of cycles to stretch the given strobe to. Must be >= 1.

        output    -- If provided, the given signal will be used as the output signal.
        domain    -- If provided, the given domain _object_ will be used in lieu of the sync domain.

     Returns the output signal. If output is provided, this is the same signal; otherwise, it is the
     signal that was created internally.
     """

    # Assume the sync domain if no domain is provided.
    if domain is None:
        domain = m.d.sync

    # If we're not given an output signal to target, create one.
    if output is None:
        output = Signal()

    # Special case: if to_cycles is '1', we don't need to modify the strobe.
    # Connect it through directly.
    if to_cycles == 1:
        m.d.comb += output.eq(strobe)
        return output

    # Create a signal that shifts in our strobe constantly, so we
    # have a memory of its last N values.
    if allow_delay:
        delayed_strobe = Signal(to_cycles)
        domain += delayed_strobe.eq((delayed_strobe << 1) | strobe)
        m.d.comb += output.eq(delayed_strobe != 0)
    else:
        delayed_strobe = Signal(to_cycles - 1)
        domain += delayed_strobe.eq((delayed_strobe << 1) | strobe)
        m.d.comb += output.eq(strobe | (delayed_strobe != 0))

    return output


class StrobeStretcherTest(LunaGatewareTestCase):
    """ Test case for our strobe stretcher function. """


    def instantiate_dut(self):
        m = Module()

        # Create a module that only has our stretched strobe signal.
        m.strobe_in = Signal()
        m.stretched_strobe = stretch_strobe_signal(m, m.strobe_in, to_cycles=2)

        return m


    def initialize_signals(self):
        yield self.dut.strobe_in.eq(0)


    @sync_test_case
    def test_stretch(self):

        # Ensure our stretched strobe stays 0 until it sees an input.
        yield
        self.assertEqual((yield self.dut.stretched_strobe), 0)
        yield
        self.assertEqual((yield self.dut.stretched_strobe), 0)

        # Apply our strobe, and validate that we immediately see a '1'...
        yield self.dut.strobe_in.eq(1)
        yield
        self.assertEqual((yield self.dut.stretched_strobe), 1)

        # ... ensure that 1 lasts for a second cycle ...
        yield self.dut.strobe_in.eq(0)
        yield
        self.assertEqual((yield self.dut.stretched_strobe), 1)

        # ... and then returns to 0.
        yield
        self.assertEqual((yield self.dut.stretched_strobe), 0)

        yield
        self.assertEqual((yield self.dut.stretched_strobe), 0)



if __name__ == "__main__":
    warnings.filterwarnings("error")
    unittest.main()

