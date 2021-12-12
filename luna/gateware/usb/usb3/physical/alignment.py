#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code adapted from ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Code for USB3 physical-layer encoding. """

from amaranth import *
from amaranth.hdl.ast import Past

from .coding   import COM, SHP, SLC, EPF, get_word_for_symbols
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

        # Inputs and outputs.
        self.sink      = USBRawSuperSpeedStream()
        self.source    = USBRawSuperSpeedStream()

        # Debug signals
        self.alignment_offset = Signal(range(4))


    @staticmethod
    def word_meets_alignment_criteria(data, ctrl):
        """ Returns true iff the given data and control appear to be correctly aligned. """

        # Our aligner is simple: we'll search for the start of a TS1/TS2 training set; which we know
        # starts with a burst of four consecutive commas.
        four_comma_data, four_comma_ctrl = get_word_for_symbols(COM, COM, COM, COM)
        return (data == four_comma_data) & (ctrl == four_comma_ctrl)



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
        # We'll check each possible alignment to see if it would produce a valid start-of-TS1/TS2;
        # ignoring any words not marked as valid.
        changing_shift = Signal()
        new_shift      = Signal(2)

        with m.If(self.sink.valid):
            possible_alignments = len(shifted_data_slices)
            for i in range(possible_alignments):
                shifted_data = shifted_data_slices[i][0:32]
                shifted_ctrl = shifted_ctrl_slices[i][0: 4]

                # If it would, we'll accept that as our alignment going forward.
                with m.If(self.word_meets_alignment_criteria(shifted_data, shifted_ctrl)):
                    m.d.ss   += shift_to_apply.eq(i)
                    m.d.comb += [
                        changing_shift  .eq(shift_to_apply != i),
                        new_shift       .eq(i)
                    ]


        #
        # Alignment application.
        #

        # Grab the shifted data/ctrl associated with our alignment.

        with m.If(changing_shift):
            m.d.ss += [
                self.source.data       .eq(shifted_data_slices[new_shift]),
                self.source.ctrl       .eq(shifted_ctrl_slices[new_shift]),
                self.source.valid      .eq(self.sink.valid),

                self.alignment_offset  .eq(new_shift),
            ]
        with m.Else():
            m.d.ss += [
                self.source.data       .eq(shifted_data_slices[shift_to_apply]),
                self.source.ctrl       .eq(shifted_ctrl_slices[shift_to_apply]),
                self.source.valid      .eq(self.sink.valid),

                self.alignment_offset  .eq(shift_to_apply),
            ]

        return m



class RxPacketAligner(RxWordAligner):
    """ Receiver word re-alignment.

    Intended to perform a post-descramble (re)-alignment to ensure that we remain aligned to words
    even if the other side does not maintain word alignment. Many links will work without this; but
    the USB3 specification does not guarantee that word-alignment will always be maintained.

    This unit corrects alignment if the link does not maintain this property.
    """


    @staticmethod
    def word_meets_alignment_criteria(data, ctrl):
        """ Returns true iff the given data and control appear to be correctly aligned. """

        # This alignment variant looks for a start of a packet, and attempts to align itself to that.
        # We'll look specifically for the start of Link Commands and Header Packets, as they can start
        # new trains of data. (The start of a Data Packet always follows a header; so anything aligned
        # to a header packet will also be aligned to the data packet.)

        start_of_header,  _  = get_word_for_symbols(SHP, SHP, SHP, EPF)
        start_of_command, _  = get_word_for_symbols(SLC, SLC, SLC, EPF)

        data_matches = (data == start_of_header) | (data == start_of_command)
        ctrl_matches = (ctrl == 0b1111)

        return data_matches & ctrl_matches
