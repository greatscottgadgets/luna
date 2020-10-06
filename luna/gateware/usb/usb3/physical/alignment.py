#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code adapted from ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Code for USB3 physical-layer encoding. """

from nmigen import *
from nmigen.hdl.ast import Past

from .coding   import COM
from ...stream import USBRawSuperSpeedStream


class RxWordAligner(Elaboratable):
    """ Receiver word alignment.

    Uses the location of COM signals in the data stream to re-position data so that the
    relevant commas always fall in the data's LSB (little endian).
    """

    def __init__(self):

        #
        # I/O port
        #
        self.align     = Signal()

        # Inputs and outputs.
        self.sink      = USBRawSuperSpeedStream()
        self.source    = USBRawSuperSpeedStream()

        # Debug signals
        self.alignment_offset = Signal(range(4))


    def elaborate(self, platform):
        m = Module()

        # Mark ourselves as always ready for new data.
        m.d.comb += self.sink.ready.eq(1)

        # Values from previous cycles.
        previous_data = Signal.like(self.sink.data)
        previous_ctrl = Signal.like(self.sink.ctrl)
        with m.If(self.sink.valid):
            m.d.ss += [
                previous_data  .eq(self.sink.data),
                previous_ctrl  .eq(self.sink.ctrl),
            ]

        previous_valid = Past(self.sink.valid, domain="ss")

        # Alignment register: stores how many words the data must be shifted by in order to
        # have correctly aligned data.
        shift_to_apply = Signal(range(4))

        #
        # Alignment shift register.
        #
        # To align our data, we'll create a conglomeration of two consecutive words;
        # and then select the chunk between those words that has the alignment correct.
        data = Cat(previous_data, self.sink.data)
        ctrl = Cat(previous_ctrl, self.sink.ctrl)

        # Create two multiplexers that allow us to select from each of our four possible alignments.
        shifted_data_slices = Array(data[8*i:] for i in range(4))
        shifted_ctrl_slices = Array(ctrl[i:]   for i in range(4))


        #
        # Alignment detection.
        #

        # Our aligner is simple: we'll search for the start of a TS1/TS2 training set; which we know
        # starts with a burst of four consecutive commas.
        four_comma_data = Repl(COM.value_const(), 4)
        four_comma_ctrl = Repl(COM.ctrl_const(),  4)

        # We'll check each possible alignment to see if it would produce a valid start-of-TS1/TS2;
        # ignoring any words not marked as valid.
        with m.If(self.sink.valid):
            possible_alignments = len(shifted_data_slices)
            for i in range(possible_alignments):
                data_matches = (shifted_data_slices[i][0:32] == four_comma_data)
                ctrl_matches = (shifted_ctrl_slices[i][0:4]  == four_comma_ctrl)

                # If it would, we'll accept that as our alignment going forward.
                with m.If(data_matches & ctrl_matches):
                    m.d.ss += shift_to_apply.eq(i)


        #
        # Alignment application.
        #

        # Grab the shifted data/ctrl associated with our alignment.
        m.d.ss += [
            self.source.data       .eq(shifted_data_slices[shift_to_apply]),
            self.source.ctrl       .eq(shifted_ctrl_slices[shift_to_apply]),
            self.source.valid      .eq(self.sink.valid),

            self.alignment_offset  .eq(shift_to_apply),
        ]

        return m
