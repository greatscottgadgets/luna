#
# This file is part of LUNA.
#
""" Simple utility constructs for LUNA. """

from nmigen import *


def _single_edge_detector(m, signal, edge='rising'):
    """ Generates and returns a signal that goes high for a cycle upon a given edge of a given signal. """

    # Create a one-cycle delayed version of our input signal.
    delayed = Signal()
    m.d.sync += delayed.eq(signal) 

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


def rising_edge_detector(m, signal):
    """ Generates and returns a signal that goes high for a cycle each rising edge of a given signal. """
    return _single_edge_detector(m, signal, edge='rising')

def falling_edge_detector(m, signal):
    """ Generates and returns a signal that goes high for a cycle each rising edge of a given signal. """
    return _single_edge_detector(m, signal, edge='falling')

def any_edge_detector(m, signal):
    """ Generates and returns a signal that goes high for a cycle each rising edge of a given signal. """
    return _single_edge_detector(m, signal, edge='any')
