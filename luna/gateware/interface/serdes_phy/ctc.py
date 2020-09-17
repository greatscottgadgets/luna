#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based on ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Clock Tolerance Compensation (CTC) gateware. """

from nmigen import *

from ...usb.usb3.physical.coding import SKP, stream_word_matches_symbol
from ...usb.stream               import USBRawSuperSpeedStream



class CTCReceiveBuffer(Elaboratable):
    """ Clock Tolerance Compensation (CTC) elastic receive buffer gateware.

    It's functionally impossible to precisely synchronize the clocks for two independent
    systems -- every specification has to allow for some difference in frequency between
    the system's clocks (the "clock tolerance")

    To compensate, high speed serial protocols inject 'filler' bytes called "SKP ordered sets",
    which can be safely discarded. This allows the slower clock to catch up to the faster one.

    This module automatically removes those SKP ordered sets
    """

    def __init__(self):

        #
        # I/O port
        #
        self.sink          = USBRawSuperSpeedStream()
        self.source        = USBRawSuperSpeedStream()

        self.skp_removed   = Signal()


    def elaborate(self, platform):
        m = Module()

        sink   = self.sink
        source = self.source

        bytes_in_stream = len(sink.ctrl)

        #
        # Find SKP symbols
        #

        # Identify the locations of any SKP symbols present in the stream.
        skp_locations = Signal(bytes_in_stream)
        for i in range(bytes_in_stream):
            m.d.comb += skp_locations[i].eq(stream_word_matches_symbol(sink, i, symbol=SKP))

        # If we've found one, indicate that we're removing it.
        skip_found = self.sink.valid & self.sink.ready & (skp_locations != 0)
        m.d.comb += self.skp_removed.eq(skip_found)


        #
        # Data Extractor
        #

        # We'll first extract the data and control bits for every position that doesn't contain a SKP.
        valid_data        = Signal.like(sink.data)
        valid_ctrl        = Signal.like(sink.ctrl)
        valid_byte_count  = Signal(range(0, bytes_in_stream + 1))

        # We have a SKIP location for each byte; and each locations has two possible values
        # (SKP, no SKP); and therefore we have 2 ** <bytes> distinct arrangements.
        possible_arrangement_count = 2 ** bytes_in_stream
        possible_arrangements = range(possible_arrangement_count)

        # We'll handle each possibility with a programmatically generated case.
        with m.Switch(skp_locations):

            # We'll generate a single case for each possible "skip mask".
            for skip_mask in possible_arrangements:
                with m.Case(skip_mask):
                    data_fragments = []
                    ctrl_fragments = []

                    # We'll iterate over each of our possible positions, and gather
                    # the nMigen signals associated with the non-skip values in the
                    # relevant position.
                    for position in range(bytes_in_stream):

                        # If this case would have a valid byte at the given position, grab it.
                        position_mask = 1 << position
                        if (position_mask & position) == 0:
                            data_signal_at_position = sink.data.word_select(position, 8)
                            ctrl_signal_at_position = sink.ctrl.word_select(position, 8)
                            data_fragments.append(data_signal_at_position)
                            ctrl_fragments.append(ctrl_signal_at_position)


                    # If there are any valid data signals associated with the given position,
                    # coalesce the data and control signals into a single word, which we'll handle below.
                    if data_fragments:
                        m.d.comb += [
                            valid_data.eq(Cat(*data_fragments)),
                            valid_ctrl.eq(Cat(*ctrl_fragments)),
                            valid_byte_count.eq(len(data_fragments)),
                        ]


        #
        # Elastic Buffer / Valid Data Coalescence
        #

        # We now have a signal that contains up to a valid word of data. We'll need to
        # stitch this data together before we can use it. To do so, we'll use a shift
        # register long enough to store two complete words of data -- one for the word
        # we're outputting, and one for a word-in-progress.

        # This shift register serves as our "elastic buffer" -- we can add in data in
        # bits and pieces, and remove it in bits and pieces.
        buffer_size_bytes = bytes_in_stream * 2

        data_buffer     = Signal(buffer_size_bytes * 8)
        ctrl_buffer     = Signal(buffer_size_bytes)
        bytes_in_buffer = Signal(range(0, buffer_size_bytes + 1))

        m.d.comb += sink.ready.eq(bytes_in_buffer <= buffer_size_bytes)


        with m.If(sink.valid & sink.ready):

            with m.If(source.valid & source.ready):
                m.d.ss += sr_bytes.eq(sr_bytes + frag_bytes - 4)
            with m.Else():
                m.d.ss += sr_bytes.eq(sr_bytes + frag_bytes)

            with m.Switch(frag_bytes):

                with m.Case(0):
                    m.d.ss += [
                        sr_data.eq(sr_data),
                        sr_ctrl.eq(sr_ctrl),
                    ]

                for i in range(1, 5):
                    with m.Case(i):
                        m.d.ss += [
                            sr_data.eq(Cat(sr_data[8*i:], frag_data[0:8*i])),
                            sr_ctrl.eq(Cat(sr_ctrl[1*i:], frag_ctrl[0:1*i])),
                        ]


        with m.Elif(source.valid & source.ready):
            m.d.ss += sr_bytes.eq(sr_bytes - 4)


        # Output Data/Ctrl when there is a full 32/4-bit word --------------------------------------
        m.d.comb += source.valid.eq(sr_bytes >= 4)
        cases = {}

        with m.Switch(sr_bytes):
            for i in range(4, 8):
                with m.Case(i):
                    m.d.comb += [
                        source.data.eq(sr_data[8*(8-i):8*(8-i+4)]),
                        source.ctrl.eq(sr_ctrl[1*(8-i):1*(8-i+4)]),
                    ]

        return m



class TXSKPInserter(Elaboratable):
    """TX SKP Inserter

    SKP Ordered Sets are inserted in the stream for clock compensation between partners with an
    average of 1 SKP Ordered Set every 354 symbols. This module inserts SKP Ordered Sets to the
    TX stream. SKP Ordered Sets shall not be inserted inside a packet, so this packet delimiters
    (first/last) should be used to ensure SKP are inserted only between packets and not inside.

    Note: To simplify implementation and keep alignment, 2 SKP Ordered Sets are inserted every 708
    symbols, which is a small deviation from the specification (good average, but 2x interval between
    SKPs). More tests need to be done to ensure this deviation is acceptable with all hardwares.
    """
    def __init__(self):
        #
        # I/O port
        #
        self.sink   = USBRawSuperSpeedStream()
        self.source = USBRawSuperSpeedStream()


    def elaborate(self, platform):
        m = Module()

        sink   = self.sink
        source = self.source

        data_count   = Signal(8)
        skip_grant   = Signal(reset=1)
        skip_queue   = Signal()
        skip_dequeue = Signal()
        skip_count   = Signal(16)

        # Queue one 2 SKP Ordered Set every 176 Data/Ctrl words
        m.d.ss += skip_queue.eq(0)
        with m.If(sink.valid & sink.ready):
            m.d.ss += data_count.eq(data_count + 1),
            with m.If(data_count == 175):
                m.d.ss += [
                    data_count.eq(0),
                    skip_queue.eq(1)
                ]

        # SKP grant: SKP should not be inserted inside packets
        with m.If(sink.valid & sink.ready):
            with m.If(sink.last):
                m.d.ss += skip_grant.eq(1)
            with m.Elif(sink.first):
                m.d.ss += skip_grant.eq(0)


        # SKP counter
        with m.If(skip_queue & ~skip_dequeue):
            m.d.ss += skip_count.eq(skip_count + 1)
        with m.If(~skip_queue &  skip_dequeue):
            m.d.ss += skip_count.eq(skip_count - 1)


        # SKP insertion
        with m.If(skip_grant & (skip_count != 0)):
            m.d.comb += [
                source.valid.eq(1),
                source.data.eq(Repl(Signal(8, reset=SKP.value), 4)),
                source.ctrl.eq(Repl(Signal(1, reset=1)        , 4)),
                skip_dequeue.eq(source.ready)
            ]
        with m.Else():
            m.d.comb +=  sink.connect(source)

        return m
