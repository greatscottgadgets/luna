#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based on ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause


from nmigen import *

#
# TODO: get rid of this trivial timer
#

class WaitTimer(Elaboratable):
    def __init__(self, t):
        self._reset_value = t

        #
        # I/O port
        #
        self.wait = Signal()
        self.done = Signal()


    def elaborate(self, platform):
        m = Module()

        count = Signal(range(self._reset_value + 1), reset=self._reset_value)
        m.d.comb += self.done.eq(count == 0)

        with m.If(self.wait):
            with m.If(~self.done):
                m.d.ss += count.eq(count - 1)
            with m.Else():
                m.d.ss += count.eq(self._reset_value)

        return m
