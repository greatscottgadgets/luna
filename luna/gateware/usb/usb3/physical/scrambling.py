#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based on ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Scrambling and descrambling for USB3. """

from nmigen import *

from .coding   import COM
from ...stream import USBRawSuperSpeedStream

#
# Scrambling modules.
# See [USB3.2r1: Appendix B].
#

class ScramblerLFSR(Elaboratable):
    """ Scrambler LFSR.

    Linear feedback shift register used for USB3 scrambling.
    Polynomial: X^16 + X^5 + X^4 + X^3 + 1

    See [USB3.2: Appendix B]

    Attributes
    ----------
    clear: Signal(), input
        Strobe; when high, resets the LFSR to its initial value.
    advance: Signal(), input
        Strobe; when high, the LFSR advances on each clock cycle.
    value: Signal(32), output
        The current value of the LFSR.

    Parameters
    ----------
    initial_value: 32-bit int, optional
        The initial value for the LFSR. Optional; defaults to all 1's, per the USB3 spec.
    """
    def __init__(self, initial_value=0xffff):
        self._initial_value = initial_value

        #
        # I/O port
        #
        self.clear   = Signal()
        self.advance = Signal()
        self.value   = Signal(32)


    def elaborate(self, platform):
        m = Module()

        new = Signal(16)
        cur = Signal(16, reset=self._initial_value)

        # TODO: replace me with something like the USB2 format?
        m.d.comb += [
            new[0]   .eq(cur[0]  ^ cur[6] ^ cur[8]  ^ cur[10]),
            new[1]   .eq(cur[1]  ^ cur[7] ^ cur[9]  ^ cur[11]),
            new[2]   .eq(cur[2]  ^ cur[8] ^ cur[10] ^ cur[12]),
            new[3]   .eq(cur[3]  ^ cur[6] ^ cur[8]  ^ cur[9]  ^ cur[10] ^ cur[11] ^ cur[13]),
            new[4]   .eq(cur[4]  ^ cur[6] ^ cur[7]  ^ cur[8]  ^ cur[9]  ^ cur[11] ^ cur[12] ^ cur[14]),
            new[5]   .eq(cur[5]  ^ cur[6] ^ cur[7]  ^ cur[9]  ^ cur[12] ^ cur[13] ^ cur[15]),
            new[6]   .eq(cur[0]  ^ cur[6] ^ cur[7]  ^ cur[8]  ^ cur[10] ^ cur[13] ^ cur[14]),
            new[7]   .eq(cur[1]  ^ cur[7] ^ cur[8]  ^ cur[9]  ^ cur[11] ^ cur[14] ^ cur[15]),
            new[8]   .eq(cur[0]  ^ cur[2] ^ cur[8]  ^ cur[9]  ^ cur[10] ^ cur[12] ^ cur[15]),
            new[9]   .eq(cur[1]  ^ cur[3] ^ cur[9]  ^ cur[10] ^ cur[11] ^ cur[13]),
            new[10]  .eq(cur[0] ^ cur[2] ^ cur[4]  ^ cur[10] ^ cur[11] ^ cur[12] ^ cur[14]),
            new[11]  .eq(cur[1] ^ cur[3] ^ cur[5]  ^ cur[11] ^ cur[12] ^ cur[13] ^ cur[15]),
            new[12]  .eq(cur[2] ^ cur[4] ^ cur[6]  ^ cur[12] ^ cur[13] ^ cur[14]),
            new[13]  .eq(cur[3] ^ cur[5] ^ cur[7]  ^ cur[13] ^ cur[14] ^ cur[15]),
            new[14]  .eq(cur[4] ^ cur[6] ^ cur[8]  ^ cur[14] ^ cur[15]),
            new[15]  .eq(cur[5] ^ cur[7] ^ cur[9]  ^ cur[15]),

            self.value[0]   .eq(cur[15]),
            self.value[1]   .eq(cur[14]),
            self.value[2]   .eq(cur[13]),
            self.value[3]   .eq(cur[12]),
            self.value[4]   .eq(cur[11]),
            self.value[5]   .eq(cur[10]),
            self.value[6]   .eq(cur[9]),
            self.value[7]   .eq(cur[8]),
            self.value[8]   .eq(cur[7]),
            self.value[9]   .eq(cur[6]),
            self.value[10]  .eq(cur[5]),
            self.value[11]  .eq(cur[4]  ^ cur[15]),
            self.value[12]  .eq(cur[3]  ^ cur[14] ^ cur[15]),
            self.value[13]  .eq(cur[2]  ^ cur[13] ^ cur[14] ^ cur[15]),
            self.value[14]  .eq(cur[1]  ^ cur[12] ^ cur[13] ^ cur[14]),
            self.value[15]  .eq(cur[0]  ^ cur[11] ^ cur[12] ^ cur[13]),
            self.value[16]  .eq(cur[10] ^ cur[11] ^ cur[12] ^ cur[15]),
            self.value[17]  .eq(cur[9]  ^ cur[10] ^ cur[11] ^ cur[14]),
            self.value[18]  .eq(cur[8]  ^ cur[9]  ^ cur[10] ^ cur[13]),
            self.value[19]  .eq(cur[7]  ^ cur[8]  ^ cur[9]  ^ cur[12]),
            self.value[20]  .eq(cur[6]  ^ cur[7]  ^ cur[8]  ^ cur[11]),
            self.value[21]  .eq(cur[5]  ^ cur[6]  ^ cur[7]  ^ cur[10]),
            self.value[22]  .eq(cur[4]  ^ cur[5]  ^ cur[6]  ^ cur[9]  ^ cur[15]),
            self.value[23]  .eq(cur[3]  ^ cur[4]  ^ cur[5]  ^ cur[8]  ^ cur[14]),
            self.value[24]  .eq(cur[2]  ^ cur[3]  ^ cur[4]  ^ cur[7]  ^ cur[13] ^ cur[15]),
            self.value[25]  .eq(cur[1]  ^ cur[2]  ^ cur[3]  ^ cur[6]  ^ cur[12] ^ cur[14]),
            self.value[26]  .eq(cur[0]  ^ cur[1]  ^ cur[2]  ^ cur[5]  ^ cur[11] ^ cur[13] ^ cur[15]),
            self.value[27]  .eq(cur[0]  ^ cur[1]  ^ cur[4]  ^ cur[10] ^ cur[12] ^ cur[14]),
            self.value[28]  .eq(cur[0]  ^ cur[3]  ^ cur[9]  ^ cur[11] ^ cur[13]),
            self.value[29]  .eq(cur[2]  ^ cur[8]  ^ cur[10] ^ cur[12]),
            self.value[30]  .eq(cur[1]  ^ cur[7]  ^ cur[9]  ^ cur[11]),
            self.value[31]  .eq(cur[0]  ^ cur[6]  ^ cur[8]  ^ cur[10]),
        ]

        # If we have a reset, clear our LFSR.
        with m.If(self.clear):
            m.d.ss += cur.eq(self._initial_value)

        # Otherwise, advance when desired.
        with m.Elif(self.advance):
            m.d.ss += cur.eq(new)

        return m



class Scrambler(Elaboratable):
    """ USB3-compliant data scrambler.

    Scrambles the transmitted data stream to reduce EMI.

    Attributes
    ----------
    clear: Signal(), input
        Strobe; when high, resets the scrambler to the start of its sequence.
    enable: Signal(), input
        When high, data scrambling is enabled. When low, data is passed through without scrambling.
    sink: USBRawSuperSpeedStream(), input stream
        The stream containing data to be scrambled.
    sink: USBRawSuperSpeedStream(), output stream
        The stream containing data the scrambled output.

    Parameters
    ----------
    initial_value: 32-bit int, optional
        The initial value for the LFSR. Optional.
    """
    def __init__(self, initial_value=0x7dbd):
        self._initial_value = initial_value

        #
        # I/O port
        #
        self.clear  = Signal()
        self.enable = Signal(reset=1)
        self.sink   = USBRawSuperSpeedStream()
        self.source = USBRawSuperSpeedStream()


    def elaborate(self, platform):
        m = Module()

        sink   = self.sink
        source = self.source

        # Create our inner LFSR, which should advance whenever our input streams do.
        m.submodules.lfsr = lfsr = ScramblerLFSR(initial_value=self._initial_value)
        m.d.comb += [
            lfsr.clear    .eq(self.clear),
            lfsr.advance  .eq(sink.valid & sink.ready)
        ]

        # Default to passing through all data directly...
        m.d.comb += source.stream_eq(sink)

        # If we have any non-control words, scramble them by overriding our data assignment above
        # with the relevant data word XOR'd with our LFSR value. Note that control words are -never-
        # scrambled, per [USB3.2: Appendix B]
        for i in range(4):
            is_data_code = ~sink.ctrl[i]
            lfsr_word    = lfsr.value.word_select(i, 8)

            with m.If(self.enable & is_data_code):
                m.d.comb += source.data.word_select(i, 8).eq(sink.data.word_select(i, 8) ^ lfsr_word)

        return m



class Descrambler(Elaboratable):
    """ USB3-compliant data descrambler.

    This module descrambles the received data stream. K-codes are not affected.
    This module automatically resets itself whenever a COM alignment character is seen.

    Attributes
    ----------
    enable: Signal(), input
        When high, data scrambling is enabled. When low, data is passed through without scrambling.
    sink: USBRawSuperSpeedStream(), input stream
        The stream containing data to be descrambled.
    sink: USBRawSuperSpeedStream(), output stream
        The stream containing data the descrambled output.

    Parameters
    ----------
    initial_value: 32-bit int, optional
        The initial value for the LFSR. Optional.

    """
    def __init__(self, initial_value=0xffff):
        self._initial_value = initial_value

        #
        # I/O port
        #
        self.enable = Signal(reset=1)
        self.sink   = USBRawSuperSpeedStream()
        self.source = USBRawSuperSpeedStream()


    def elaborate(self, platform):
        m = Module()

        sink   = self.sink
        source = self.source

        # Create an internal scrambler. Because scrambling is accomplished by XOR'ing with a fixed
        # LFSR stream; we can use the same hardware for scrambling and our core descrambling.
        m.submodules.scrambler = scrambler = Scrambler(initial_value=self._initial_value)
        m.d.comb += [
            scrambler.enable  .eq(self.enable),

            scrambler.sink    .stream_eq(sink),
            source            .stream_eq(scrambler.source)
        ]

        #
        # Automatically reset our internal scrambler when receiving COM signals.
        #
        for i in range(4):
            symbol_is_com = (sink.data.word_select(i, 8) == COM.value) & sink.ctrl[i]

            with m.If(sink.valid & sink.ready & symbol_is_com):
                m.d.comb += scrambler.clear.eq(1)

        return m
