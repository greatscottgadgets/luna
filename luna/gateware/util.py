#
# This file is part of LUNA.
#
""" Simple utility constructs for LUNA. """

import unittest
from .test.utils import LunaGatewareTestCase, sync_test_case

from nmigen import Module, Signal, Cat

def _single_edge_detector(m, signal, *, edge='rising', domain=None):
    """ Generates and returns a signal that goes high for a cycle upon a given edge of a given signal. """

    if domain is None:
        domain = m.d.sync

    # Create a one-cycle delayed version of our input signal.
    delayed = Signal()
    domain += delayed.eq(signal)

    # And create a signal that detects edges on the relevant signal.
    edge_detected = Signal()
    if edge == 'falling':
        m.d.comb += edge_detected.eq(delayed & ~signal)
    elif edge == 'rising':
        m.d.comb += edge_detected.eq(~delayed & signal)
    elif edge == 'any':
        m.d.comb += edge_detected.eq(delayed != signal)
    else:
        raise ValueError("edge must be one of {rising,falling,any}")

    return edge_detected


def rising_edge_detector(m, signal, *, domain=None):
    """ Generates and returns a signal that goes high for a cycle each rising edge of a given signal. """
    return _single_edge_detector(m, signal, edge='rising', domain=domain)

def falling_edge_detector(m, signal, *, domain=None):
    """ Generates and returns a signal that goes high for a cycle each rising edge of a given signal. """
    return _single_edge_detector(m, signal, edge='falling', domain=domain)

def any_edge_detector(m, signal, *, domain=None):
    """ Generates and returns a signal that goes high for a cycle each rising edge of a given signal. """
    return _single_edge_detector(m, signal, edge='any', domain=domain)


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
    unittest.main()
