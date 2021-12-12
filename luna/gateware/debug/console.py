#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Simple gateware debug console for LUNA. """


from amaranth        import Signal, Module, Cat, Elaboratable, Array
from ..test.utils    import LunaGatewareTestCase, sync_test_case


class DebugConsole(Elaboratable):
    """ Simple debug console gateware for LUNA.

        I: line_in[8][max_line_legth] -- The line to be rendered to the output stream.
        I: line_length -- The data length to be rendered t

    """

    def __init__(self, *, max_line_length=128):

        self.line_in     = Array(Signal(8) for _ in range(max_line_length))
        self.line_length = Signal(range(0, max_line_length + 1))


    def elaborate(self, platform):
        m = Module()

        return m
