# amaranth: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Helpers for clock domain crossings. """

from amaranth       import Signal


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
