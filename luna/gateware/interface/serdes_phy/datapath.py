#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based on ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Abstract SerDes interfacing code.

See also the FPGA family-specific SerDes backends located in the `backends` subfolder.
"""

import unittest

from amaranth import *
from amaranth.lib.cdc  import FFSynchronizer, PulseSynchronizer, ResetSynchronizer
from amaranth.lib.fifo import AsyncFIFOBuffered
from amaranth.hdl.ast  import Past

from ...test.utils import LunaGatewareTestCase, sync_test_case
from ...usb.stream import USBRawSuperSpeedStream

from ...usb.usb3.physical.coding import K, COM, SKP


#
# Receiver gateware
#

class ReceiverGearbox(Elaboratable):
    """ Simple rate-halving gearbox for our receive path.

    Designed specifically for our receive path; always halves the frequency of the input;
    and ignores "readiness", as the SerDes is always constantly producing output.

    If :attr:``output_domain`` is provided, clock domain crossing is handled automatically.

    Attributes
    ----------
    sink: input stream
        The full-rate stream to be geared down.
    source: output stream
        The half-rate stream, post-gearing.

    Parameters
    ----------
    words_in: int, optional
        The number of words of data to be processed at once; each word includes one byte of data and one
        bit of control. Output will always be twice this value. Defaults to 2.
    input_domain: str
        The name of the clock domain that our :attr:``sink`` resides in. Defaults to `rx`.
    output_domain: str, or None
        The name of the clock domain that our :attr:``source`` resides in. If not provided, no CDC
        hardware will be generated.
    """

    def __init__(self, words_in=2, input_domain="rx", output_domain=None, flip_bytes=True):
        self._flip_bytes      = flip_bytes
        self._words_in        = words_in
        self._data_bits_in    = words_in * 8
        self._ctrl_bits_in    = words_in
        self._input_domain    = input_domain
        self._output_domain   = output_domain if output_domain else input_domain

        #
        # I/O port
        #
        self.sink   = USBRawSuperSpeedStream(payload_words=words_in)
        self.source = USBRawSuperSpeedStream(payload_words=words_in * 2)


    def elaborate(self, platform):
        m = Module()

        # Buffer our stream inputs here to improve timing.
        stream_in_data  = Signal.like(self.sink.data)
        stream_in_ctrl  = Signal.like(self.sink.ctrl)
        stream_in_valid = Signal.like(self.sink.valid)
        m.d.sync += [
            stream_in_data   .eq(self.sink.data),
            stream_in_ctrl   .eq(self.sink.ctrl),
            stream_in_valid  .eq(self.sink.valid),
        ]

        # Aliases.
        stream_in  = self.sink
        if self._flip_bytes:
            stream_in_data = stream_in.data.rotate_right((self._words_in // 2) * 8)
            stream_in_ctrl = stream_in.ctrl.rotate_right(self._words_in // 2)
        else:
            stream_in_data = stream_in.data
            stream_in_ctrl = stream_in.ctrl


        # If our output domain is the same as our input domain, we'll directly drive our output stream.
        # Otherwise, we'll drive an internal signal; and then cross that into our output domain.
        if self._output_domain == self._input_domain:
            stream_out = self.source
        else:
            stream_out = USBRawSuperSpeedStream()


        # Create proxies that allow us access to the upper and lower halves of our output data stream.
        data_out_halves = Array(stream_out.data.word_select(i, self._data_bits_in) for i in range(2))
        ctrl_out_halves = Array(stream_out.ctrl.word_select(i, self._ctrl_bits_in) for i in range(2))

        # Word select -- selects whether we're targeting the upper or lower half of the output word.
        # Toggles every input-domain cycle.
        targeting_upper_half = Signal(reset=1 if self._flip_bytes else 0)
        m.d.sync += targeting_upper_half.eq(~targeting_upper_half)

        # Pass through our data and control every cycle.
        m.d.sync += [
            data_out_halves[targeting_upper_half]  .eq(stream_in_data),
            ctrl_out_halves[targeting_upper_half]  .eq(stream_in_ctrl),
        ]

        # Set our valid signal high only if both the current and previously captured word are valid.
        m.d.comb += [
            stream_out.valid  .eq(stream_in.valid & Past(stream_in.valid, domain=self._input_domain))
        ]

        if self._input_domain != self._output_domain:
            in_domain_signals  = Cat(
                stream_out.data,
                stream_out.ctrl,
                stream_out.valid
            )
            out_domain_signals = Cat(
                self.source.data,
                self.source.ctrl,
                self.source.valid
            )

            # Create our async FIFO...
            m.submodules.cdc = fifo = AsyncFIFOBuffered(
                width=len(in_domain_signals),
                depth=8,
                w_domain="sync",
                r_domain=self._output_domain
            )

            m.d.comb += [
                # ... fill it from our in-domain stream...
                fifo.w_data             .eq(in_domain_signals),
                fifo.w_en               .eq(targeting_upper_half),

                # ... and output it into our output stream.
                out_domain_signals      .eq(fifo.r_data),
                self.source.valid       .eq(fifo.r_level > 2),
                fifo.r_en               .eq(1),
            ]


        # If our source domain isn't `sync`, translate `sync` to the proper domain name.
        if self._input_domain != "sync":
            m = DomainRenamer({'sync': self._input_domain})(m)

        return m


class ReceiverSkipRemover(Elaboratable):
    """ Clock Tolerance Compensation (CTC) Skip remover.

    SKP Ordered Sets are inserted in the stream for clock compensation between partners with an
    average of 1 SKP Ordered Set every 354 symbols. This module removes SKP Ordered Sets from
    the RX stream.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.sink   = USBRawSuperSpeedStream()
        self.source = USBRawSuperSpeedStream()
        self.skip   = Signal()


    def elaborate(self, platform):
        m = Module()

        sink   = self.sink
        source = self.source

        #
        # Find SKP symbols
        #
        skp = Signal(4)
        for i in range(4):
            m.d.comb += skp[i].eq(sink.ctrl[i] & (sink.data[8*i:8*(i+1)] == SKP.value))
        m.d.comb += self.skip.eq(self.sink.valid & self.sink.ready & (skp != 0))

        #
        # Select valid Data/Ctrl fragments
        #
        frag_data  = Signal(32)
        frag_ctrl  = Signal(4)
        frag_bytes = Signal(3)

        with m.Switch(skp):
            for i in range(2**4):
                with m.Case(i):

                    datas = []
                    ctrls = []

                    for j in range(4):
                        if (i & 2**j) == 0:
                            datas.append(sink.data[8*j:8*(j+1)])
                            ctrls.append(sink.ctrl[1*j:1*(j+1)])

                    m.d.comb += [
                        frag_data.eq(Cat(*datas) if len(datas) else 0),
                        frag_ctrl.eq(Cat(*ctrls) if len(ctrls) else 0),
                        frag_bytes.eq(len(ctrls)),
                    ]

        # Store Data/Ctrl in a 64/8-bit Shift Register ---------------------------------------------
        sr_data  = Signal(64)
        sr_ctrl  = Signal(8)
        sr_bytes = Signal(4)


        m.d.comb += sink.ready.eq(sr_bytes <= 7)


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
            alignment_byte_precedence = reversed(range(4))
        else:
            alignment_byte_precedence = range(4)


        # Apply new alignments only if we're the first seen COM (since USB3 packets can contain multiple
        # consecutive COMs), and if alignment is enabled.
        following_data_byte = (previous_ctrl == 0)
        with m.If(self.align & following_data_byte):

            # Detect any alignment markers by looking for a COM signal in any of the four positions.
            for i in alignment_byte_precedence:
                data_matches = (stream_in.data.word_select(i, 8) == COM.value)
                ctrl_matches = stream_in.ctrl[i]

                # If the current position has a comma in it, mark this as our alignment position;
                # and compute how many times we'll need to rotate our data _right_ in order to achieve
                # proper alignment.
                with m.If(data_matches & ctrl_matches):
                    if self._is_big_endian:
                        m.d.ss += [
                            shift_to_apply    .eq(3 - i),
                            stream_out.valid  .eq(shift_to_apply == (3 - i))
                        ]
                    else:
                        m.d.ss += [
                            shift_to_apply  .eq(i),
                            stream_out.valid.eq(shift_to_apply == i)
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

        return m


class RxTrainingWordAligner(Elaboratable):
    """ Receiver word alignment (TS-based variant).

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
        # Alignment shift register.
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

        # We'll check each possible alignment to see if it would produce a valid start-of-TS1/TS2.
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
            stream_out.data  .eq(shifted_data_slices[shift_to_apply]),
            stream_out.ctrl  .eq(shifted_ctrl_slices[shift_to_apply]),

            # We're part of a chain that always produces data (currently);
            # so for now, we'll always indicate our data is valid. This may
            # need to be changed if we add in nicer CTC.
            stream_out.valid .eq(1),

            # Debug output.
            self.alignment_offset.eq(shift_to_apply)
        ]

        return m




class ReceivePostprocessing(Elaboratable):
    """RX Datapath

    This module realizes the:
    - Data-width adaptation (from transceiver's data-width to 32-bit).
    - Clock domain crossing (from transceiver's RX clock to system clock).
    - Clock compensation (SKP removing).
    - Words alignment.
    """
    def __init__(self, clock_domain="rx", buffer_clock_domain="fast",
            output_clock_domain="ss", serdes_is_little_endian=True):

        self._clock_domain            = clock_domain
        self._buffer_clock_domain     = buffer_clock_domain
        self._output_clock_domain     = output_clock_domain
        self._serdes_is_little_endian = serdes_is_little_endian

        #
        # I/O port
        #
        self.align  = Signal()
        self.sink   = USBRawSuperSpeedStream(payload_words=2)
        self.source = USBRawSuperSpeedStream(payload_words=4)

        # Debug signals
        self.alignment_offset = Signal(range(4))


    def elaborate(self, platfrom):
        m = Module()

        #
        # 1:2 Gearing (and clock domain crossing).
        #
        m.submodules.gearing = gearing = ReceiverGearbox(
            input_domain  = self._clock_domain,
            output_domain = "ss",
            flip_bytes    = self._serdes_is_little_endian
        )
        m.d.comb += gearing.sink.stream_eq(self.sink)

        #
        # Clock tolerance compensation.
        #
        #m.submodules.skip_remover = skip_remover = ReceiverSkipRemover()
        #m.d.comb += skip_remover.sink.stream_eq(gearing.source)

        #
        # Word aligner.
        #
        #m.submodules.word_aligner = word_aligner = RxWordAligner()
        m.submodules.word_aligner = word_aligner = RxTrainingWordAligner()
        m.d.comb += [
            #  Core outputs
            word_aligner.align      .eq(self.align),
            word_aligner.sink       .stream_eq(gearing.source),

            # Debug output.
            self.alignment_offset   .eq(word_aligner.alignment_offset)

        ]

        #
        # Final output.
        #
        m.d.comb += self.source.stream_eq(word_aligner.source)

        return m


#
# Transmitter gateware
#


class TransmitterGearbox(Elaboratable):
    """ Simple rate-doubling gearbox for our transmit path.

    Designed specifically for our transmit path; always doubles the frequency of the input;
    and ignores "readiness", as the SerDes is always constantly producing output.

    If :attr:``output_domain`` is provided, clock domain crossing is handled automatically.

    Attributes
    ----------
    sink: input stream
        The single-rate stream to be geared up.
    source: output stream
        The double-rate stream, post-gearing.

    Parameters
    ----------
    words_in: int, optional
        The number of words of data to be processed at once; each word includes one byte of data and one
        bit of control. Output will always be twice this value. Defaults to 4.
    output_domain: str
        The name of the clock domain that our :attr:``source`` resides in. Defaults to `tx`.
    input_domain: str, or None
        The name of the clock domain that our :attr:``sink`` resides in. If not provided, no CDC
        hardware will be generated.
    """

    def __init__(self, words_in=4, output_domain="tx", input_domain=None):
        self._ratio           = 2
        self._flip_bytes      = True
        self._words_in        = words_in
        self._words_out       = words_in // 2
        self._output_domain   = output_domain
        self._input_domain    = input_domain if input_domain else output_domain

        #
        # I/O port
        #
        self.sink   = USBRawSuperSpeedStream(payload_words=self._words_in)
        self.source = USBRawSuperSpeedStream(payload_words=self._words_out)


    def elaborate(self, platform):
        m = Module()

        # If we're receiving data from an domain other than our output domain,
        # cross it over nicely.
        if self._input_domain != self._output_domain:
            stream_in = USBRawSuperSpeedStream(payload_words=self._words_in)
            in_domain_signals  = Cat(
                self.sink.data,
                self.sink.ctrl,
            )
            out_domain_signals = Cat(
                stream_in.data,
                stream_in.ctrl,
            )

            # Advance our FIFO only ever other cycle.
            advance_fifo = Signal()
            m.d.tx += advance_fifo.eq(~advance_fifo)

            # Create our async FIFO...
            m.submodules.cdc = fifo = AsyncFIFOBuffered(
                width=len(in_domain_signals),
                depth=8,
                w_domain=self._input_domain,
                r_domain="tx"
            )

            m.d.comb += [
                # ... fill it from our in-domain stream...
                fifo.w_data             .eq(in_domain_signals),
                fifo.w_en               .eq(1),
                self.sink.ready         .eq(1),

                # ... and output it into our output stream.
                out_domain_signals      .eq(fifo.r_data),
                stream_in.valid         .eq(fifo.r_rdy),
                fifo.r_en               .eq(advance_fifo),
            ]

        # Otherwise, use our data-stream directly.
        else:
            stream_in = self.sink
            m.d.comb += self.sink.ready.eq(1)


        # Word select -- selects whether we're targeting the upper or lower half of the input word.
        # Toggles every input-domain cycle.
        next_half_targeted   = Signal()
        targeting_upper_half = Signal()

        # If our data has just changed, we should always be targeting the upper word.
        # This "locks" us to the data's changes.
        data_changed = stream_in.data != Past(stream_in.data, domain="tx")
        ctrl_changed = stream_in.ctrl != Past(stream_in.ctrl, domain="tx")
        with m.If(data_changed | ctrl_changed):
            m.d.comb += targeting_upper_half  .eq(1 if self._flip_bytes else 0)
            m.d.tx   += next_half_targeted    .eq(0 if self._flip_bytes else 1)
        with m.Else():
            m.d.comb += targeting_upper_half  .eq(next_half_targeted)
            m.d.tx   += next_half_targeted    .eq(~next_half_targeted)


        # If we're flipping the bytes in our output stream (e.g. to maintain endianness),
        # create a flipped version; otherwise, use our output stream directly.
        stream_out = self.source

        # Create proxies that allow us access to the upper and lower halves of our input data stream.
        data_in_halves = Array(stream_in.data.word_select(i, len(stream_in.data) // 2) for i in range(2))
        ctrl_in_halves = Array(stream_in.ctrl.word_select(i, len(stream_in.ctrl) // 2) for i in range(2))

        # Pass through our data and control every cycle.
        # This is registered to loosen timing.
        if self._flip_bytes:
            stream_out_data = data_in_halves[targeting_upper_half]
            stream_out_ctrl = ctrl_in_halves[targeting_upper_half]
            m.d.tx += [
                stream_out.data  .eq(stream_out_data.rotate_right(len(stream_out_data) // 2)),
                stream_out.ctrl  .eq(stream_out_ctrl.rotate_right(len(stream_out_ctrl) // 2)),
                stream_out.valid .eq(1),
            ]
        else:
            m.d.tx += [
                stream_out.data  .eq(data_in_halves[targeting_upper_half]),
                stream_out.ctrl  .eq(ctrl_in_halves[targeting_upper_half]),
                stream_out.valid .eq(1),
            ]

        # If our output domain isn't `sync`, translate `sync` to the proper domain name.
        if self._output_domain != "tx":
            m = DomainRenamer({'tx': self._output_domain})(m)

        return m


class TransmitterGearboxTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = TransmitterGearbox
    FRAGMENT_ARGUMENTS = {'output_domain': 'sync'}

    @sync_test_case
    def test_basic_gearbox(self):
        dut    = self.dut
        sink   = dut.sink
        source = dut.source

        # If we start off with our stream presenting COM, 0xFF, 0x17, 0xC0.
        yield sink.data.eq(0xBCFF17C0)
        yield sink.ctrl.eq(0b1000)

        # After a two-cycle pipeline delay, we should see the first word on our output...
        yield from self.advance_cycles(2)
        self.assertEqual((yield source.data), 0xFFBC)
        self.assertEqual((yield source.ctrl), 0b01)
        yield sink.data.eq(0x14B2E702)
        yield sink.ctrl.eq(0b0000)

        # ... followed by the second...
        yield from self.advance_cycles(1)
        self.assertEqual((yield source.data), 0xC017)
        self.assertEqual((yield source.ctrl), 0b00)

        # ... and our data should continue changing with the input.
        yield from self.advance_cycles(1)
        self.assertEqual((yield source.data), 0xB214)
        self.assertEqual((yield source.ctrl), 0b00)
        yield from self.advance_cycles(1)
        self.assertEqual((yield source.data), 0x02E7)
        self.assertEqual((yield source.ctrl), 0b00)





# RXErrorSubstitution (6.3.5) ----------------------------------------------------------------------

#class RXErrorSubstitution(Module):
#    """RX Error Substitution
#
#    Substitutes 8b/10b decoder errors with K28.4 symbols.
#    """
#    def __init__(self, serdes, clock_domain):
#        self.sink   = USBRawSuperSpeedStream(payload_words=2)
#        self.source = USBRawSuperSpeedStream(payload_words=2)
#
#        # # #
#
#        self.comb += self.sink.connect(self.source)
#        for i in range(2):
#            self.comb += [
#                If(serdes.decoders[i].invalid,
#                    self.source.ctrl[i].eq(1),
#                    self.source.data[8*i:8*(i+1)].eq(K(28, 4)),
#                )
#            ]

# TX SKP Inserter (6.4.3) --------------------------------------------------------------------------

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


class TransmitPreprocessing(Elaboratable):
    """TX Datapath

    This module realizes the:
    - Clock compensation (SKP insertion).
    - Clock domain crossing (from system clock to transceiver's TX clock).
    - Data-width adaptation (from 32-bit to transceiver's data-width).
    """
    def __init__(self, clock_domain="sync"):
        self.sink   = USBRawSuperSpeedStream(payload_words=4)
        self.source = USBRawSuperSpeedStream(payload_words=2)


    def elaborate(self, platform):
        m = Module()

        #
        # Clock tolerance compensation
        #
        #m.submodules.skip_inserter = skip_inserter = TXSKPInserter()
        #m.d.comb += skip_inserter.sink.stream_eq(self.sink)


        #
        # Output gearing (& clock-domain crossing)
        #
        m.submodules.gearing = gearing = TransmitterGearbox(
            output_domain = "tx",
            input_domain  = "ss",
        )
        m.d.comb += gearing.sink.stream_eq(self.sink)
        #self.comb += gearing.sink.stream_eq(skip_inserter.source)

        #
        # Final output
        #
        m.d.comb += self.source.stream_eq(gearing.source)

        return m



if __name__ == "__main__":
    unittest.main()
