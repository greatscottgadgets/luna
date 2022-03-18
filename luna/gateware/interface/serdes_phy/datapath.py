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
        targeting_upper_half = Signal(reset=1 if self._flip_bytes else 0)
        with m.If(stream_in.valid):
            # Toggles every input-domain cycle.
            m.d.sync += targeting_upper_half.eq(~targeting_upper_half)

            # Pass through our data and control every cycle.
            m.d.sync += [
                data_out_halves[targeting_upper_half]  .eq(stream_in_data),
                ctrl_out_halves[targeting_upper_half]  .eq(stream_in_ctrl),
            ]

        # Set our valid signal high only if both the current and previously captured word are valid.
        m.d.comb += [
            stream_out.valid  .eq(stream_in.valid & targeting_upper_half)
        ]

        if self._input_domain != self._output_domain:
            in_domain_signals  = Cat(
                stream_out.data,
                stream_out.ctrl,
            )
            out_domain_signals = Cat(
                self.source.data,
                self.source.ctrl,
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
                fifo.w_en               .eq(stream_out.valid),

                # ... and output it into our output stream.
                out_domain_signals      .eq(fifo.r_data),
                fifo.r_en               .eq(1),
                self.source.valid       .eq(fifo.r_rdy),
            ]


        # If our source domain isn't `sync`, translate `sync` to the proper domain name.
        if self._input_domain != "sync":
            m = DomainRenamer({'sync': self._input_domain})(m)

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
        m.d.comb += self.source.stream_eq(gearing.source)

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
                fifo.w_en               .eq(self.sink.valid),
                self.sink.ready         .eq(fifo.w_rdy),

                # ... and output it into our output stream.
                out_domain_signals      .eq(fifo.r_data),
                stream_in.valid         .eq(fifo.r_rdy),
                fifo.r_en               .eq(advance_fifo),
            ]

        # Otherwise, use our data-stream directly.
        else:
            stream_in = self.sink

            # Read from our input stream only ever other cycle.
            m.d.tx += self.sink.ready.eq(~self.sink.ready)


        # Word select -- selects whether we're targeting the upper or lower half of the input word.
        # Toggles every input-domain cycle.
        next_half_targeted   = Signal()
        targeting_upper_half = Signal()

        # If our data has just changed, we should always be targeting the upper word.
        # This "locks" us to the data's changes.
        data_changed = stream_in.data != Past(stream_in.data, domain=self._output_domain)
        ctrl_changed = stream_in.ctrl != Past(stream_in.ctrl, domain=self._output_domain)
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


class TransmitPreprocessing(Elaboratable):
    """TX Datapath

    This module realizes the:
    - Clock compensation (SKP insertion/removal).
    - Clock domain crossing (from system clock to transceiver's TX clock).
    - Data-width adaptation (from 32-bit to transceiver's data-width).
    """
    def __init__(self, clock_domain="sync"):
        self.sink   = USBRawSuperSpeedStream(payload_words=4)
        self.source = USBRawSuperSpeedStream(payload_words=2)


    def elaborate(self, platform):
        m = Module()

        #
        # Output gearing (& clock-domain crossing)
        #
        m.submodules.gearing = gearing = TransmitterGearbox(
            output_domain = "tx",
            input_domain  = "ss")
        m.d.comb += gearing.sink.stream_eq(self.sink)

        #
        # Final output
        #
        m.d.comb += self.source.stream_eq(gearing.source)

        return m



if __name__ == "__main__":
    unittest.main()
