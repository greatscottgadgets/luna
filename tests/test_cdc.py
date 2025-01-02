# amaranth: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test         import LunaGatewareTestCase, sync_test_case
from unittest       import TestCase

from amaranth import Module, Signal
from luna.gateware.utils.cdc import stretch_strobe_signal


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
