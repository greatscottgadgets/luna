#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code adapted from ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Code for handling SKP ordered sets on the transmit and receive path.

SKP ordered sets are provided in order to give some "padding data" that can be removed
in order to handle differences in transmitter/receiver clock rates -- a process called
"clock tolerance compensation" (CTC). The actual insertion and removal of SKP ordered sets
for CTC is handled by the PHY -- but it only adds and removes sets where it needs to to
compensate for clock differences.

It's up to us to insert and remove additional ordered sets.
"""

import unittest

from amaranth import *

from .coding import SKP, stream_word_matches_symbol
from ...stream import USBRawSuperSpeedStream

from ....test.utils import LunaSSGatewareTestCase, ss_domain_test_case

class CTCSkipRemover(Elaboratable):
    """ Clock Tolerance Compensation (CTC) receive buffer gateware.

    It's functionally impossible to precisely synchronize the clocks for two independent
    systems -- every specification has to allow for some difference in frequency between
    the system's clocks (the "clock tolerance")

    To compensate, high speed serial protocols inject 'filler' bytes called "SKP ordered sets",
    which can be safely discarded. This allows the slower clock to catch up to the faster one.
    [USB 3.2r1: 6.4.3].

    Our PHY handles the core clock tolerance compesnation inside of its own clock domain; removing
    these filler sets whenever removing them helps to keep the receiver and transmitter's clocks in sync.
    This leaves behind the sets whose removal would not directly help with CTC.

    This module removes those leftovers before data leaves the physical layer.

    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input stream
        The stream from which SKP ordered sets should be removed.
    source: USBRawSuperSpeedStream(), output stream
        The relevant stream with SKP ordered sets removed. Note that past this point,
        ``stream.valid`` can and will sometimes be false.

    skip_removed: Signal(), output
        Strobe that indicates that a SKP ordered set was removed.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.sink            = USBRawSuperSpeedStream()
        self.source          = USBRawSuperSpeedStream()

        self.skip_removed    = Signal()
        self.bytes_in_buffer = Signal(range(len(self.sink.ctrl) + 1))


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
        m.d.comb += self.skip_removed.eq(skip_found)


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
                    # the Amaranth signals associated with the non-skip values in the
                    # relevant position.
                    for position in range(bytes_in_stream):

                        # If this case would have a valid byte at the given position, grab it.
                        position_mask = 1 << position
                        if (position_mask & skip_mask) == 0:
                            data_signal_at_position = sink.data.word_select(position, 8)
                            ctrl_signal_at_position = sink.ctrl[position]
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

        # This shift register serves as a local "elastic buffer" -- we can add in data in
        # bits and pieces, and remove it in bits and pieces.
        buffer_size_bytes = bytes_in_stream * 2

        # Create our internal shift register, as well as our current fill counter.
        data_buffer     = Signal(buffer_size_bytes * 8)
        ctrl_buffer     = Signal(buffer_size_bytes)
        bytes_in_buffer = Signal(range(0, buffer_size_bytes + 1))

        # Determine if we'll have a valid stream
        m.d.comb += sink.ready.eq(bytes_in_buffer <= buffer_size_bytes)

        # If we're receiving data this round, add it into our shift register.
        with m.If(sink.valid & sink.ready):

            # Compute how many bytes we'll have next cycle: it's the number of bytes we already have
            # (bytes_in_buffer) plus the bytes we're adding (valid_byte_count) and minus the data we're
            # about to remove (one word, or bytes_in_stream) if we're reading, or minus nothing if we're not.
            with m.If(source.valid & source.ready):
                m.d.ss += bytes_in_buffer.eq(bytes_in_buffer + valid_byte_count - bytes_in_stream)
            with m.Else():
                m.d.ss += bytes_in_buffer.eq(bytes_in_buffer + valid_byte_count)

            # Handle our shift register pushing logic.
            with m.Switch(valid_byte_count):

                # Our simplest case: we have no data in the buffer; and nothing needs to change.
                with m.Case(0):
                    pass

                # In every other case, we have some data to be added to the buffer.
                # We'll do the math slightly differently for each potential number of bytes.
                for i in range(1, bytes_in_stream + 1):
                    with m.Case(i):

                        # Grab our existing data, and stick it onto the end of the shift register.
                        m.d.ss += [
                            data_buffer  .eq(Cat(data_buffer[8*i:], valid_data[0:8*i])),
                            ctrl_buffer  .eq(Cat(ctrl_buffer[1*i:], valid_ctrl[0:1*i])),
                        ]

        # If we're not receiving data, but we -are- removing it, we'll just update our total
        # valid data counter to account for the removal.
        with m.Elif(source.valid & source.ready):
            m.d.ss += bytes_in_buffer.eq(bytes_in_buffer - bytes_in_stream)


        #
        # Data output
        #

        # We'll output a word each time we have enough data in our shift register toS
        # output a full word.
        m.d.comb += source.valid.eq(bytes_in_buffer >= bytes_in_stream)

        # Our data ends in different places depending on how many bytes we
        # have in our shift register; so we'll need to pop it from different locations.
        with m.Switch(bytes_in_buffer):
            for i in range(bytes_in_stream, bytes_in_stream * 2):
                with m.Case(i):
                    # Grab the relevant word from the end of the buffer.
                    word_position = 8 - i
                    m.d.comb += [
                        source.data.eq(data_buffer[8 * word_position : 8 * (word_position + bytes_in_stream)]),
                        source.ctrl.eq(ctrl_buffer[1 * word_position : 1 * (word_position + bytes_in_stream)]),
                    ]

        #
        # Diagnostic output.
        #
        m.d.comb += self.bytes_in_buffer.eq(bytes_in_buffer)

        return m



class CTCSkipRemoverTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = CTCSkipRemover

    def initialize_signals(self):
        # Set up our streams to always ferry data in and out, where possible.
        yield self.dut.sink.valid.eq(1)
        yield self.dut.source.ready.eq(1)


    def provide_input(self, data, ctrl):
        yield self.dut.sink.data.eq(data)
        yield self.dut.sink.ctrl.eq(ctrl)
        yield


    @ss_domain_test_case
    def test_dual_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x71BA3C3C, 0b0011)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x11223344, 0b1100)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield
        self.assertEqual((yield source.data), 0x334471BA)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x33441122)
        self.assertEqual((yield source.ctrl), 0b11)


    @ss_domain_test_case
    def test_shifted_dual_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x713C3CBA, 0b0110)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x113C3C44, 0b0110)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield from self.provide_input(0x55667788, 0b0000)
        self.assertEqual((yield source.data), 0x114471BA)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x55667788)
        self.assertEqual((yield source.ctrl), 0)


    @ss_domain_test_case
    def test_single_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x3C556677, 0b1000)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x11223344, 0b1100)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield
        self.assertEqual((yield source.data), 0x44556677)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x44112233)
        self.assertEqual((yield source.ctrl), 0b110)


    @ss_domain_test_case
    def test_cycle_spread_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x3C556677, 0b1000)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x1122333C, 0b0001)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield from self.provide_input(0x44556677, 0b0000)
        self.assertEqual((yield source.data), 0x33556677)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x66771122)
        self.assertEqual((yield source.ctrl), 0b0)



class CTCSkipInserter(Elaboratable):
    """ Clock Tolerance Compensation (CTC) Skip insertion gateware.

    See the ``CTCSkipRemover`` for a description of CTC and its general operation.

    Our PHY handles the core clock tolerance compesnation inside of its own clock domain; adding
    Skip sets whenever adding them helps to keep the transmitter's elastic buffer from running low
    on data. However, we still need to add in our own Skip ordered sets so the other side of the link
    has enough to perform its own CTC adjustments.

    This module adds ordered sets, per the USB standard.

    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input stream
        The stream into which SKP ordered sets should be inserted.
    source: USBRawSuperSpeedStream(), output stream
        The relevant stream with SKP ordered sets inserted.

    can_send_skip: Signal(), input
        Controls when SKPs can be inserted. This should be asserted when we're transmitting
        logical idle.

    sending_skip: Signal(), output
        Indicates that we're currently sending only SKP characters; and thus our scrambler
        should not advance.
    """

    SKIP_BYTE_LIMIT = 354

    def __init__(self):
        #
        # I/O port
        #
        self.sink          = USBRawSuperSpeedStream()
        self.source        = USBRawSuperSpeedStream()

        self.can_send_skip = Signal()
        self.sending_skip  = Signal()


    def elaborate(self, platform):
        m = Module()

        sink   = self.sink
        source = self.source

        #
        # SKP scheduling.
        #

        # The largest amount of pending SKP ordered sets can right before finishing transmitting:
        #   (20 bytes of DPH) + (1036 bytes of DPP) + (6 bytes of SKP)
        # This sequence is 1062, or 354*3, bytes long. Since we only transmit pairs of SKP ordered sets,
        # the maximum amount of pending SKP ordered sets at any time is 4.
        skips_to_send = Signal(range(5))
        skip_needed   = Signal()

        # Precisely count the amount of skip ordered sets that will be inserted at the next opportunity.
        # From [USB3.0r1: 6.4.3]: "The non-integer remainder of the Y/354 SKP calculation shall not be
        # discarded and shall be used in the calculation to schedule the next SKP Ordered Set."
        with m.If(skip_needed & ~self.sending_skip):
            m.d.ss += skips_to_send.eq(skips_to_send + 1)
        with m.If(~skip_needed & self.sending_skip):
            m.d.ss += skips_to_send.eq(skips_to_send - 2)
        with m.If(skip_needed & self.sending_skip):
            m.d.ss += skips_to_send.eq(skips_to_send - 1)


        #
        # SKP insertion timing.
        #
        bytes_per_word = len(self.sink.ctrl)
        data_bytes_elapsed = Signal(range(self.SKIP_BYTE_LIMIT))

        # Count each byte of data we send...
        with m.If(sink.valid & sink.ready):
            m.d.ss += data_bytes_elapsed.eq(data_bytes_elapsed + bytes_per_word)

            # ... and once we see enough data, schedule insertion of a skip ordered set.
            with m.If(data_bytes_elapsed + bytes_per_word >= self.SKIP_BYTE_LIMIT):
                m.d.ss   += data_bytes_elapsed.eq(data_bytes_elapsed + bytes_per_word - self.SKIP_BYTE_LIMIT)
                m.d.comb += skip_needed.eq(1)


        #
        # SKP insertion.
        #

        # Finally, if we can send a skip this cycle and need to, replace our IDLE with two SKP ordered sets.
        #
        # Although [USB3.0r1: 6.4.3] allows "during training only [...] the option of waiting to insert 2 SKP
        # ordered sets when the integer result of Y/354 reaches 2", inserting individual SKP ordered sets on
        # a 32-bit data path has considerable overhead, and we only insert pairs.
        with m.If(self.can_send_skip & (skips_to_send >= 2)):
            m.d.comb += self.sending_skip.eq(1)
            m.d.ss += [
                source.valid       .eq(1),
                source.data        .eq(Repl(SKP.value_const(), len(source.ctrl))),
                source.ctrl        .eq(Repl(SKP.ctrl_const(),  len(source.ctrl))),
            ]

        with m.Else():
            m.d.ss += [
                self.source        .stream_eq(self.sink),
            ]

        return m


if __name__ == "__main__":
    unittest.main()
