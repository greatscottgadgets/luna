# nmigen: UnusedElaboratable=no
#
# This file is part of LUNA.
#
""" Helpers for clock domain crossings. """

import unittest
import warnings

from unittest       import TestCase
from nmigen         import Record, Module, Signal
from nmigen.lib.cdc import FFSynchronizer
from nmigen.hdl.rec import DIR_FANIN, DIR_FANOUT

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
        output = signal.like(signal)

    # Trivial case: if this element doesn't have a layout,
    # we can just synchronize it directly.
    if not hasattr(signal, 'layout'):
        m.submodules += create_synchronizer(signal, output)
        return output

    # Otherwise, we'll need to make sure we only synchronize
    # elements with non-output directions.
    for name, layout, direction in signal.layout:

        # If this is a record itself, we'll need to recurse.
        if isinstance(signal[name], Record) and (len(layout.fields) > 1):
            synchronize(m, signal[name], output=output[name],
                    o_domain=o_domain, stages=stages)

        # Skip any output elements, as they're already
        # in our clock domain, and we don't want to drive them.
        if (direction == DIR_FANOUT) or hasattr(signal[name], 'o'):
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


if __name__ == "__main__":
    warnings.filterwarnings("error")
    unittest.main()
