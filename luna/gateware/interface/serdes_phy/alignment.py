#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based on ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" SerDes stream word alignment code. """

from nmigen import *
from nmigen.lib.fifo import AsyncFIFOBuffered
from nmigen.hdl.ast  import Past

from ...usb.stream import USBRawSuperSpeedStream
from ...usb.usb3.physical.coding import COM


class RxWordAligner(Elaboratable):
    """ Receiver word alignment.

    Uses the location of COM signals in the data stream to re-position data so that the
    relevant commas always fall in the data's MSB (big endian).
    """

    def __init__(self):
        self._is_big_endian = True

        #
        # I/O port
        #
        self.align  = Signal()
        self.sink   = USBRawSuperSpeedStream()
        self.source = USBRawSuperSpeedStream()

        # Debug signals
        self.alignment_offset = Signal(range(4))


    def elaborate(self, platform):
        m = Module()

        # Aliases
        stream_in   = self.sink
        stream_out  = self.source

        # Values from previous cycles.
        previous_data = Past(stream_in.data, domain="ss")
        previous_ctrl = Past(stream_in.ctrl, domain="ss")

        # Alignment register: stores how many words the data must be shifted by in order to
        # have correctly aligned data.
        shift_to_apply = Signal(range(4))

        #
        # Alignment detector.
        #

        if self._is_big_endian:
            alignment_precedence = range(4)
        else:
            alignment_precedence = reversed(range(4))


        # Apply new alignments only if we're the first seen COM (since USB3 packets can contain multiple
        # consecutive COMs), and if alignment is enabled.
        following_data_byte = (previous_ctrl == 0)
        with m.If(self.align & following_data_byte):

            # Detect any alignment markers by looking for a COM signal in any of the four positions.
            for i in alignment_precedence:
                data_matches = (stream_in.data.word_select(i, 8) == COM.value)
                ctrl_matches = stream_in.ctrl[i]

                # If the current position has a comma in it, mark this as our alignment position;
                # and compute how many times we'll need to rotate our data _right_ in order to achieve
                # proper alignment.
                with m.If(data_matches & ctrl_matches):
                    if self._is_big_endian:
                        m.d.ss += [
                            shift_to_apply    .eq(3 - i),
                            #stream_out.valid  .eq(shift_to_apply == (3 - i))
                        ]
                    else:
                        m.d.ss += [
                            shift_to_apply  .eq(i),
                            #stream_out.valid.eq(shift_to_apply == i)
                        ]



        #
        # Aligner.
        #

        # To align our data, we'll create a conglomeration of two consecutive words;
        # and then select the chunk between those words that has the alignment correct.
        # (These words should always be in chronological order; so we'll need different
        # orders for big endian and little endian output.)
        if self._is_big_endian:
            data = Cat(stream_in.data, previous_data)
            ctrl = Cat(stream_in.ctrl, previous_ctrl)
        else:
            data = Cat(previous_data, stream_in.data)
            ctrl = Cat(previous_ctrl, stream_in.ctrl)

        # Create two multiplexers that allow us to select from each of our four possible
        # alignments...
        shifted_data_slices = Array(data[8*i:] for i in range(4))
        shifted_ctrl_slices = Array(ctrl[i:]   for i in range(4))

        # ... and output our data accordingly.
        m.d.ss += [
            stream_out.data  .eq(shifted_data_slices[shift_to_apply]),
            stream_out.ctrl  .eq(shifted_ctrl_slices[shift_to_apply]),

            # Debug output.
            self.alignment_offset.eq(shift_to_apply)

        ]

        # XXX: test
        m.d.comb += [
            self.source.valid.eq(1)
        ]


        return m
