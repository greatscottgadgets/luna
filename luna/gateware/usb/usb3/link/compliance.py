#
# This file is part of LUNA.
#
# Copyright (c) 2026 Great Scott Gadgets <info@greatscottgadgets.com>
#
# SPDX-License-Identifier: BSD-3-Clause
""" Compliance pattern generation gateware.
"""

from collections import namedtuple

from amaranth import *

from ..physical.coding import NamedSymbol, D, K, COM, IDL
from ...stream         import USBRawSuperSpeedStream

Pattern = namedtuple(
    'Pattern',
    ['value', 'ctrl', 'scrambling', 'lfps', 'deemphasis', 'oneszeros'],
    defaults=[0, 0, False, False, True, False],
)

PATTERNS = [
    Pattern(IDL.value, IDL.ctrl, scrambling=True), # CP0: D0.0 scrambled
    Pattern(D(10, 2)),                             # CP1: Nyquist frequency
    Pattern(D(24, 3)),                             # CP2: Nyquist/2
    Pattern(COM.value, COM.ctrl),                  # CP3: COM pattern
    Pattern(lfps=True),                            # CP4: LFPS
    Pattern(K(27, 7), ctrl=1),                     # CP5: K27.7 with de-emphasis
    Pattern(K(27, 7), ctrl=1, deemphasis=False),   # CP6: K27.7 without de-emphasis
    Pattern(oneszeros=True),                       # CP7: 50-250 ones & 50-250 zeros with de-emphasis
    Pattern(oneszeros=True, deemphasis=False),     # CP8: 50-250 ones & 50-250 zeros without de-emphasis
]


class CompliancePatternEmitter(Elaboratable):
    """ Emitter for USB3 physical layer compliance test patterns.
    """
    def __init__(self):

        #
        # I/O port
        #
        self.source             = USBRawSuperSpeedStream()

        self.enable             = Signal()
        self.enable_scrambling  = Signal()
        self.lfps_ping_detected = Signal()
        self.send_lfps_polling  = Signal()
        self.disable_deemph     = Signal()
        self.tx_ones_zeros      = Signal()



    def elaborate(self, platform):
        m = Module()

        current_pattern = Signal(range(len(PATTERNS)))

        with m.If(self.lfps_ping_detected):
            m.d.sync += current_pattern.eq(current_pattern + 1)
            with m.If(current_pattern == len(PATTERNS) - 1):
                m.d.sync += current_pattern.eq(0)

        with m.Switch(current_pattern):
            for i, pattern in enumerate(PATTERNS):
                with m.Case(i):
                    with m.If(self.enable):
                        m.d.comb += [
                            self.source.valid     .eq(1),
                            self.source.data      .eq(C(pattern.value, 8).replicate(4)),
                            self.source.ctrl      .eq(C(pattern.ctrl,  1).replicate(4)),
                            self.enable_scrambling.eq(pattern.scrambling),
                            self.send_lfps_polling.eq(pattern.lfps),
                            self.disable_deemph   .eq(~pattern.deemphasis),
                            self.tx_ones_zeros    .eq(pattern.oneszeros),
                        ]

        return m

