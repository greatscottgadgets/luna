#
# This file is part of LUNA.
#
""" Simple utility constructs for LUNA. """

import unittest
from ..test.utils import LunaGatewareTestCase, sync_test_case

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





if __name__ == "__main__":
    unittest.main()
