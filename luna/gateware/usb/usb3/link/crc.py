#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" CRC computation gateware for USB3. """


import unittest
import operator
import functools

from amaranth import *

from ....test import LunaSSGatewareTestCase, ss_domain_test_case


def compute_usb_crc5(protected_bits):
    """ Generates a 5-bit signal equivalent to the CRC5 check of a given 11-bits.

    Intended for link command words / link control words.

    Parameters
    ----------
    protected_bits: 11-bit Signal()
        The 11-bit signal to generate a CRC5 for.

    Returns
    -------
    Signal(5)
        A five-bit signal equivalent to the CRC5 of the protected bits.
    """

    def xor_bits(*indices):
        bits = (protected_bits[len(protected_bits) - 1 - i] for i in indices)
        return functools.reduce(operator.__xor__, bits)

    # Implements the CRC polynomial from the USB specification.
    return Cat(
            xor_bits(10, 9, 8, 5, 4, 2),
           ~xor_bits(10, 9, 8, 7, 4, 3, 1),
            xor_bits(10, 9, 8, 7, 6, 3, 2, 0),
            xor_bits(10, 7, 6, 4, 1),
            xor_bits(10, 9, 6, 5, 3, 0)
    )



class HeaderPacketCRC(Elaboratable):
    """ Gateware that computes a running CRC-16 for the first three words of a header packet.

    Attributes
    ----------
    clear: Signal(), input
        Strobe; clears the CRC, restoring it to its Initial Value.

    data_input: Signal(32), input
        Data word to add to our running CRC.
    advance_crc: Signal(), input
        When asserted, the current data input will be added to the CRC.

    crc: Signal(16), output
        The current CRC value.


    Parameters
    ----------
    initial_value: int, Const
            The initial value of the CRC shift register; the USB default is used if not provided.
    """

    def __init__(self, initial_value=0xFFFF):
        self._initial_value = initial_value

        #
        # I/O port
        #
        self.clear       = Signal()

        self.data_input  = Signal(32)
        self.advance_crc = Signal()

        self.crc   = Signal(16, reset=initial_value)


    def _generate_next_crc(self, current_crc, data_in):
        """ Generates the next round of a wordwise USB CRC16. """

        def xor_data_bits(*indices):
            bits = (data_in[len(data_in) - 1 - i] for i in indices)
            return functools.reduce(operator.__xor__, bits)

        def xor_past_bits(*indices):
            bits = (current_crc[i] for i in indices)
            return functools.reduce(operator.__xor__, bits)

        # Extracted from the USB3 spec's definition of the CRC16 polynomial.
        # This is hideous, but it's lifted directly from the specification, so it's probably safer
        # not to try and "clean it up" by expanding the polynomial ourselves.
        return Cat(
            xor_past_bits(4, 5, 7, 10, 12, 13, 15)
                ^ xor_data_bits(0, 4, 8, 12, 13, 15, 20, 21, 23, 26, 28, 29, 31),
            xor_past_bits(0, 4, 6, 7, 8, 10, 11, 12, 14, 15)
                ^ xor_data_bits(0, 1, 4, 5, 8, 9, 12, 14, 15, 16, 20, 22, 23, 24, 26, 27, 28, 30, 31),
            xor_past_bits(0, 1, 5, 7, 8, 9, 11, 12, 13, 15)
                ^ xor_data_bits(1, 2, 5, 6, 9, 10, 13, 15, 16, 17, 21, 23, 24, 25, 27, 28, 29, 31),
            xor_past_bits(0, 1, 2, 4, 5, 6, 7, 8, 9, 14, 15)
                ^ xor_data_bits(0, 2, 3, 4, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 30, 31),
            xor_past_bits(0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 15)
                ^ xor_data_bits(1, 3, 4, 5, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 24, 25, 26, 31),
            xor_past_bits(0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11)
                ^ xor_data_bits(2, 4, 5, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27),
            xor_past_bits(0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12)
                ^ xor_data_bits(3, 5, 6, 7, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28),
            xor_past_bits(0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13)
                ^ xor_data_bits(4, 6, 7, 8, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 24, 25, 26, 27, 28, 29),
            xor_past_bits(0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14)
                ^ xor_data_bits(5, 7, 8, 9, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29, 30),
            xor_past_bits(0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15)
                ^ xor_data_bits(6, 8, 9, 10, 12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30, 31),
            xor_past_bits(1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15)
                ^ xor_data_bits(7, 9, 10, 11, 13, 14, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31),
            xor_past_bits(0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15)
                ^ xor_data_bits(8, 10, 11, 12, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 30, 31),
            xor_past_bits(0, 1, 3, 6, 8, 9, 11, 12, 14)
                ^ xor_data_bits(0, 4, 8, 9, 11, 16, 17, 19, 22, 24, 25, 27, 28, 30),
            xor_past_bits(1, 2, 4, 7, 9, 10, 12, 13, 15)
                ^ xor_data_bits(1, 5, 9, 10, 12, 17, 18, 20, 23, 25, 26, 28, 29, 31),
            xor_past_bits(2, 3, 5, 8, 10, 11, 13, 14)
                ^ xor_data_bits(2, 6, 10, 11, 13, 18, 19, 21, 24, 26, 27, 29, 30),
            xor_past_bits(3, 4, 6, 9, 11, 12, 14, 15)
                ^ xor_data_bits(3, 7, 11, 12, 14, 19, 20, 22, 25, 27, 28, 30, 31),
        )


    def elaborate(self, platform):
        m = Module()

        # Register that contains the running CRCs.
        crc = Signal(16, reset=self._initial_value)

        # If we're clearing our CRC in progress, move our holding register back to
        # our initial value.
        with m.If(self.clear):
            m.d.ss += crc.eq(self._initial_value)

        # Otherwise, update the CRC whenever we have new data.
        with m.Elif(self.advance_crc):
            m.d.ss += crc.eq(self._generate_next_crc(crc, self.data_input))

        # Convert from our intermediary "running CRC" format into the current CRC-16...
        m.d.comb += self.crc.eq(~crc[::-1])

        return m



class DataPacketPayloadCRC(Elaboratable):
    """ Gateware that computes a running CRC-32 for a data packet payload.

    This CRC is more complicated than others, as Data Packet Payloads are not
    required to end on a word boundary. Accordingly, we'll need to handle cases
    where we have an incomplete word of 1, 2, or 3 bytes.

    Attributes
    ----------
    clear: Signal(), input
        Strobe; clears the CRC, restoring it to its Initial Value.

    data_input: Signal(32), input
        Data word to add to our running CRC.

    advance_word: Signal(), input
        When asserted, the current data word will be added to our CRC.
    advance_3B: Signal(), input
        When asserted, the last three bytes of the current data word will be added to our CRC.
    advance_2B: Signal(), input
        When asserted, the last two bytes of the current data word will be added to our CRC.
    advance_1B: Signal(), input
        When asserted, the last byte of the current data word will be added to our CRC.

    crc: Signal(32), output
        The current CRC value.

    next_crc_3B: Signal(32), output
        The CRC value for the next cycle, assuming we advance 3B.
    next_crc_2B: Signal(32), output
        The CRC value for the next cycle, assuming we advance 2B.
    next_crc_1B: Signal(32), output
        The CRC value for the next cycle, assuming we advance 1B.


    Parameters
    ----------
    initial_value: int, Const
            The initial value of the CRC shift register; the USB default is used if not provided.
    """

    def __init__(self, initial_value=0xFFFFFFFF):
        self._initial_value = initial_value

        #
        # I/O port
        #
        self.clear        = Signal()

        self.data_input   = Signal(32)
        self.advance_word = Signal()
        self.advance_3B   = Signal()
        self.advance_2B   = Signal()
        self.advance_1B   = Signal()

        self.crc         = Signal(32)
        self.next_crc_3B = Signal(32)
        self.next_crc_2B = Signal(32)
        self.next_crc_1B = Signal(32)


    def _generate_next_full_crc(self, current_crc, data_in):
        """ Generates the next round of our CRC; given a full input word . """

        # Helper functions that help us more clearly match the expanded polynomial form.
        d = lambda i : data_in[len(data_in) - i - 1]
        q = lambda i : current_crc[i]

        # These lines are extremely long, but there doesn't seem any advantage in clarity to splitting them.
        return Cat(
            q(0) ^ q(6) ^ q(9) ^ q(10) ^ q(12) ^ q(16) ^ q(24) ^ q(25) ^ q(26) ^ q(28) ^ q(29) ^ q(30) ^ q(31) ^ d(0) ^ d(6) ^ d(9) ^ d(10) ^ d(12) ^ d(16) ^ d(24) ^ d(25) ^ d(26) ^ d(28) ^ d(29) ^ d(30) ^ d(31),
            q(0) ^ q(1) ^ q(6) ^ q(7) ^ q(9) ^ q(11) ^ q(12) ^ q(13) ^ q(16) ^ q(17) ^ q(24) ^ q(27) ^ q(28) ^ d(0) ^ d(1) ^ d(6) ^ d(7) ^ d(9) ^ d(11) ^ d(12) ^ d(13) ^ d(16) ^ d(17) ^ d(24) ^ d(27) ^ d(28),
            q(0) ^ q(1) ^ q(2) ^ q(6) ^ q(7) ^ q(8) ^ q(9) ^ q(13) ^ q(14) ^ q(16) ^ q(17) ^ q(18) ^ q(24) ^ q(26) ^ q(30) ^ q(31) ^ d(0) ^ d(1) ^ d(2) ^ d(6) ^ d(7) ^ d(8) ^ d(9) ^ d(13) ^ d(14) ^ d(16) ^ d(17) ^ d(18) ^ d(24) ^ d(26) ^ d(30) ^ d(31),
            q(1) ^ q(2) ^ q(3) ^ q(7) ^ q(8) ^ q(9) ^ q(10) ^ q(14) ^ q(15) ^ q(17) ^ q(18) ^ q(19) ^ q(25) ^ q(27) ^ q(31) ^ d(1) ^ d(2) ^ d(3) ^ d(7) ^ d(8) ^ d(9) ^ d(10) ^ d(14) ^ d(15) ^ d(17) ^ d(18) ^ d(19) ^ d(25) ^ d(27) ^ d(31),
            q(0) ^ q(2) ^ q(3) ^ q(4) ^ q(6) ^ q(8) ^ q(11) ^ q(12) ^ q(15) ^ q(18) ^ q(19) ^ q(20) ^ q(24) ^ q(25) ^ q(29) ^ q(30) ^ q(31) ^ d(0) ^ d(2) ^ d(3) ^ d(4) ^ d(6) ^ d(8) ^ d(11) ^ d(12) ^ d(15) ^ d(18) ^ d(19) ^ d(20) ^ d(24) ^ d(25) ^ d(29) ^ d(30) ^ d(31),
            q(0) ^ q(1) ^ q(3) ^ q(4) ^ q(5) ^ q(6) ^ q(7) ^ q(10) ^ q(13) ^ q(19) ^ q(20) ^ q(21) ^ q(24) ^ q(28) ^ q(29) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(5) ^ d(6) ^ d(7) ^ d(10) ^ d(13) ^ d(19) ^ d(20) ^ d(21) ^ d(24) ^ d(28) ^ d(29),
            q(1) ^ q(2) ^ q(4) ^ q(5) ^ q(6) ^ q(7) ^ q(8) ^ q(11) ^ q(14) ^ q(20) ^ q(21) ^ q(22) ^ q(25) ^ q(29) ^ q(30) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6) ^ d(7) ^ d(8) ^ d(11) ^ d(14) ^ d(20) ^ d(21) ^ d(22) ^ d(25) ^ d(29) ^ d(30),
            q(0) ^ q(2) ^ q(3) ^ q(5) ^ q(7) ^ q(8) ^ q(10) ^ q(15) ^ q(16) ^ q(21) ^ q(22) ^ q(23) ^ q(24) ^ q(25) ^ q(28) ^ q(29) ^ d(0) ^ d(2) ^ d(3) ^ d(5) ^ d(7) ^ d(8) ^ d(10) ^ d(15) ^ d(16) ^ d(21) ^ d(22) ^ d(23) ^ d(24) ^ d(25) ^ d(28) ^ d(29),
            q(0) ^ q(1) ^ q(3) ^ q(4) ^ q(8) ^ q(10) ^ q(11) ^ q(12) ^ q(17) ^ q(22) ^ q(23) ^ q(28) ^ q(31) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(8) ^ d(10) ^ d(11) ^ d(12) ^ d(17) ^ d(22) ^ d(23) ^ d(28) ^ d(31),
            q(1) ^ q(2) ^ q(4) ^ q(5) ^ q(9) ^ q(11) ^ q(12) ^ q(13) ^ q(18) ^ q(23) ^ q(24) ^ q(29) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(9) ^ d(11) ^ d(12) ^ d(13) ^ d(18) ^ d(23) ^ d(24) ^ d(29),
            q(0) ^ q(2) ^ q(3) ^ q(5) ^ q(9) ^ q(13) ^ q(14) ^ q(16) ^ q(19) ^ q(26) ^ q(28) ^ q(29) ^ q(31) ^ d(0) ^ d(2) ^ d(3) ^ d(5) ^ d(9) ^ d(13) ^ d(14) ^ d(16) ^ d(19) ^ d(26) ^ d(28) ^ d(29) ^ d(31),
            q(0) ^ q(1) ^ q(3) ^ q(4) ^ q(9) ^ q(12) ^ q(14) ^ q(15) ^ q(16) ^ q(17) ^ q(20) ^ q(24) ^ q(25) ^ q(26) ^ q(27) ^ q(28) ^ q(31) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(9) ^ d(12) ^ d(14) ^ d(15) ^ d(16) ^ d(17) ^ d(20) ^ d(24) ^ d(25) ^ d(26) ^ d(27) ^ d(28) ^ d(31),
            q(0) ^ q(1) ^ q(2) ^ q(4) ^ q(5) ^ q(6) ^ q(9) ^ q(12) ^ q(13) ^ q(15) ^ q(17) ^ q(18) ^ q(21) ^ q(24) ^ q(27) ^ q(30) ^ q(31) ^ d(0) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6) ^ d(9) ^ d(12) ^ d(13) ^ d(15) ^ d(17) ^ d(18) ^ d(21) ^ d(24) ^ d(27) ^ d(30) ^ d(31),
            q(1) ^ q(2) ^ q(3) ^ q(5) ^ q(6) ^ q(7) ^ q(10) ^ q(13) ^ q(14) ^ q(16) ^ q(18) ^ q(19) ^ q(22) ^ q(25) ^ q(28) ^ q(31) ^ d(1) ^ d(2) ^ d(3) ^ d(5) ^ d(6) ^ d(7) ^ d(10) ^ d(13) ^ d(14) ^ d(16) ^ d(18) ^ d(19) ^ d(22) ^ d(25) ^ d(28) ^ d(31),
            q(2) ^ q(3) ^ q(4) ^ q(6) ^ q(7) ^ q(8) ^ q(11) ^ q(14) ^ q(15) ^ q(17) ^ q(19) ^ q(20) ^ q(23) ^ q(26) ^ q(29) ^ d(2) ^ d(3) ^ d(4) ^ d(6) ^ d(7) ^ d(8) ^ d(11) ^ d(14) ^ d(15) ^ d(17) ^ d(19) ^ d(20) ^ d(23) ^ d(26) ^ d(29),
            q(3) ^ q(4) ^ q(5) ^ q(7) ^ q(8) ^ q(9) ^ q(12) ^ q(15) ^ q(16) ^ q(18) ^ q(20) ^ q(21) ^ q(24) ^ q(27) ^ q(30) ^ d(3) ^ d(4) ^ d(5) ^ d(7) ^ d(8) ^ d(9) ^ d(12) ^ d(15) ^ d(16) ^ d(18) ^ d(20) ^ d(21) ^ d(24) ^ d(27) ^ d(30),
            q(0) ^ q(4) ^ q(5) ^ q(8) ^ q(12) ^ q(13) ^ q(17) ^ q(19) ^ q(21) ^ q(22) ^ q(24) ^ q(26) ^ q(29) ^ q(30) ^ d(0) ^ d(4) ^ d(5) ^ d(8) ^ d(12) ^ d(13) ^ d(17) ^ d(19) ^ d(21) ^ d(22) ^ d(24) ^ d(26) ^ d(29) ^ d(30),
            q(1) ^ q(5) ^ q(6) ^ q(9) ^ q(13) ^ q(14) ^ q(18) ^ q(20) ^ q(22) ^ q(23) ^ q(25) ^ q(27) ^ q(30) ^ q(31) ^ d(1) ^ d(5) ^ d(6) ^ d(9) ^ d(13) ^ d(14) ^ d(18) ^ d(20) ^ d(22) ^ d(23) ^ d(25) ^ d(27) ^ d(30) ^ d(31),
            q(2) ^ q(6) ^ q(7) ^ q(10) ^ q(14) ^ q(15) ^ q(19) ^ q(21) ^ q(23) ^ q(24) ^ q(26) ^ q(28) ^ q(31) ^ d(2) ^ d(6) ^ d(7) ^ d(10) ^ d(14) ^ d(15) ^ d(19) ^ d(21) ^ d(23) ^ d(24) ^ d(26) ^ d(28) ^ d(31),
            q(3) ^ q(7) ^ q(8) ^ q(11) ^ q(15) ^ q(16) ^ q(20) ^ q(22) ^ q(24) ^ q(25) ^ q(27) ^ q(29) ^ d(3) ^ d(7) ^ d(8) ^ d(11) ^ d(15) ^ d(16) ^ d(20) ^ d(22) ^ d(24) ^ d(25) ^ d(27) ^ d(29),
            q(4) ^ q(8) ^ q(9) ^ q(12) ^ q(16) ^ q(17) ^ q(21) ^ q(23) ^ q(25) ^ q(26) ^ q(28) ^ q(30) ^ d(4) ^ d(8) ^ d(9) ^ d(12) ^ d(16) ^ d(17) ^ d(21) ^ d(23) ^ d(25) ^ d(26) ^ d(28) ^ d(30),
            q(5) ^ q(9) ^ q(10) ^ q(13) ^ q(17) ^ q(18) ^ q(22) ^ q(24) ^ q(26) ^ q(27) ^ q(29) ^ q(31) ^ d(5) ^ d(9) ^ d(10) ^ d(13) ^ d(17) ^ d(18) ^ d(22) ^ d(24) ^ d(26) ^ d(27) ^ d(29) ^ d(31),
            q(0) ^ q(9) ^ q(11) ^ q(12) ^ q(14) ^ q(16) ^ q(18) ^ q(19) ^ q(23) ^ q(24) ^ q(26) ^ q(27) ^ q(29) ^ q(31) ^ d(0) ^ d(9) ^ d(11) ^ d(12) ^ d(14) ^ d(16) ^ d(18) ^ d(19) ^ d(23) ^ d(24) ^ d(26) ^ d(27) ^ d(29) ^ d(31),
            q(0) ^ q(1) ^ q(6) ^ q(9) ^ q(13) ^ q(15) ^ q(16) ^ q(17) ^ q(19) ^ q(20) ^ q(26) ^ q(27) ^ q(29) ^ q(31) ^ d(0) ^ d(1) ^ d(6) ^ d(9) ^ d(13) ^ d(15) ^ d(16) ^ d(17) ^ d(19) ^ d(20) ^ d(26) ^ d(27) ^ d(29) ^ d(31),
            q(1) ^ q(2) ^ q(7) ^ q(10) ^ q(14) ^ q(16) ^ q(17) ^ q(18) ^ q(20) ^ q(21) ^ q(27) ^ q(28) ^ q(30) ^ d(1) ^ d(2) ^ d(7) ^ d(10) ^ d(14) ^ d(16) ^ d(17) ^ d(18) ^ d(20) ^ d(21) ^ d(27) ^ d(28) ^ d(30),
            q(2) ^ q(3) ^ q(8) ^ q(11) ^ q(15) ^ q(17) ^ q(18) ^ q(19) ^ q(21) ^ q(22) ^ q(28) ^ q(29) ^ q(31) ^ d(2) ^ d(3) ^ d(8) ^ d(11) ^ d(15) ^ d(17) ^ d(18) ^ d(19) ^ d(21) ^ d(22) ^ d(28) ^ d(29) ^ d(31),
            q(0) ^ q(3) ^ q(4) ^ q(6) ^ q(10) ^ q(18) ^ q(19) ^ q(20) ^ q(22) ^ q(23) ^ q(24) ^ q(25) ^ q(26) ^ q(28) ^ q(31) ^ d(0) ^ d(3) ^ d(4) ^ d(6) ^ d(10) ^ d(18) ^ d(19) ^ d(20) ^ d(22) ^ d(23) ^ d(24) ^ d(25) ^ d(26) ^ d(28) ^ d(31),
            q(1) ^ q(4) ^ q(5) ^ q(7) ^ q(11) ^ q(19) ^ q(20) ^ q(21) ^ q(23) ^ q(24) ^ q(25) ^ q(26) ^ q(27) ^ q(29) ^ d(1) ^ d(4) ^ d(5) ^ d(7) ^ d(11) ^ d(19) ^ d(20) ^ d(21) ^ d(23) ^ d(24) ^ d(25) ^ d(26) ^ d(27) ^ d(29),
            q(2) ^ q(5) ^ q(6) ^ q(8) ^ q(12) ^ q(20) ^ q(21) ^ q(22) ^ q(24) ^ q(25) ^ q(26) ^ q(27) ^ q(28) ^ q(30) ^ d(2) ^ d(5) ^ d(6) ^ d(8) ^ d(12) ^ d(20) ^ d(21) ^ d(22) ^ d(24) ^ d(25) ^ d(26) ^ d(27) ^ d(28) ^ d(30),
            q(3) ^ q(6) ^ q(7) ^ q(9) ^ q(13) ^ q(21) ^ q(22) ^ q(23) ^ q(25) ^ q(26) ^ q(27) ^ q(28) ^ q(29) ^ q(31) ^ d(3) ^ d(6) ^ d(7) ^ d(9) ^ d(13) ^ d(21) ^ d(22) ^ d(23) ^ d(25) ^ d(26) ^ d(27) ^ d(28) ^ d(29) ^ d(31),
            q(4) ^ q(7) ^ q(8) ^ q(10) ^ q(14) ^ q(22) ^ q(23) ^ q(24) ^ q(26) ^ q(27) ^ q(28) ^ q(29) ^ q(30) ^ d(4) ^ d(7) ^ d(8) ^ d(10) ^ d(14) ^ d(22) ^ d(23) ^ d(24) ^ d(26) ^ d(27) ^ d(28) ^ d(29) ^ d(30),
            q(5) ^ q(8) ^ q(9) ^ q(11) ^ q(15) ^ q(23) ^ q(24) ^ q(25) ^ q(27) ^ q(28) ^ q(29) ^ q(30) ^ q(31) ^ d(5) ^ d(8) ^ d(9) ^ d(11) ^ d(15) ^ d(23) ^ d(24) ^ d(25) ^ d(27) ^ d(28) ^ d(29) ^ d(30) ^ d(31),
        )


    def _generate_next_3B_crc(self, current_crc, data_in):
        """ Generates the next round of our CRC; given a 3B trailing input word . """

        # Helper functions that help us more clearly match the expanded polynomial form.
        d = lambda i : data_in[len(data_in) - i - 1]
        q = lambda i : current_crc[i]

        # These lines are extremely long, but there doesn't seem any advantage in clarity to splitting them.
        return Cat(
            q(8) ^ q(14) ^ q(17) ^ q(18) ^ q(20) ^ q(24) ^ d(0) ^ d(6) ^ d(9) ^ d(10) ^ d(12) ^ d(16),
            q(8) ^ q(9) ^ q(14) ^ q(15) ^ q(17) ^ q(19) ^ q(20) ^ q(21) ^ q(24) ^ q(25) ^ d(0) ^ d(1) ^ d(6) ^ d(7) ^ d(9) ^ d(11) ^ d(12) ^ d(13) ^ d(16) ^ d(17),
            q(8) ^ q(9) ^ q(10) ^ q(14) ^ q(15) ^ q(16) ^ q(17) ^ q(21) ^ q(22) ^ q(24) ^ q(25) ^ q(26) ^ d(0) ^ d(1) ^ d(2) ^ d(6) ^ d(7) ^ d(8) ^ d(9) ^ d(13) ^ d(14) ^ d(16) ^ d(17) ^ d(18),
            q(9) ^ q(10) ^ q(11) ^ q(15) ^ q(16) ^ q(17) ^ q(18) ^ q(22) ^ q(23) ^ q(25) ^ q(26) ^ q(27) ^ d(1) ^ d(2) ^ d(3) ^ d(7) ^ d(8) ^ d(9) ^ d(10) ^ d(14) ^ d(15) ^ d(17) ^ d(18) ^ d(19),
            q(8) ^ q(10) ^ q(11) ^ q(12) ^ q(14) ^ q(16) ^ q(19) ^ q(20) ^ q(23) ^ q(26) ^ q(27) ^ q(28) ^ d(0) ^ d(2) ^ d(3) ^ d(4) ^ d(6) ^ d(8) ^ d(11) ^ d(12) ^ d(15) ^ d(18) ^ d(19) ^ d(20),
            q(8) ^ q(9) ^ q(11) ^ q(12) ^ q(13) ^ q(14) ^ q(15) ^ q(18) ^ q(21) ^ q(27) ^ q(28) ^ q(29) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(5) ^ d(6) ^ d(7) ^ d(10) ^ d(13) ^ d(19) ^ d(20) ^ d(21),
            q(9) ^ q(10) ^ q(12) ^ q(13) ^ q(14) ^ q(15) ^ q(16) ^ q(19) ^ q(22) ^ q(28) ^ q(29) ^ q(30) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6) ^ d(7) ^ d(8) ^ d(11) ^ d(14) ^ d(20) ^ d(21) ^ d(22),
            q(8) ^ q(10) ^ q(11) ^ q(13) ^ q(15) ^ q(16) ^ q(18) ^ q(23) ^ q(24) ^ q(29) ^ q(30) ^ q(31) ^ d(0) ^ d(2) ^ d(3) ^ d(5) ^ d(7) ^ d(8) ^ d(10) ^ d(15) ^ d(16) ^ d(21) ^ d(22) ^ d(23),
            q(8) ^ q(9) ^ q(11) ^ q(12) ^ q(16) ^ q(18) ^ q(19) ^ q(20) ^ q(25) ^ q(30) ^ q(31) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(8) ^ d(10) ^ d(11) ^ d(12) ^ d(17) ^ d(22) ^ d(23),
            q(9) ^ q(10) ^ q(12) ^ q(13) ^ q(17) ^ q(19) ^ q(20) ^ q(21) ^ q(26) ^ q(31) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(9) ^ d(11) ^ d(12) ^ d(13) ^ d(18) ^ d(23),
            q(8) ^ q(10) ^ q(11) ^ q(13) ^ q(17) ^ q(21) ^ q(22) ^ q(24) ^ q(27) ^ d(0) ^ d(2) ^ d(3) ^ d(5) ^ d(9) ^ d(13) ^ d(14) ^ d(16) ^ d(19),
            q(8) ^ q(9) ^ q(11) ^ q(12) ^ q(17) ^ q(20) ^ q(22) ^ q(23) ^ q(24) ^ q(25) ^ q(28) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(9) ^ d(12) ^ d(14) ^ d(15) ^ d(16) ^ d(17) ^ d(20),
            q(8) ^ q(9) ^ q(10) ^ q(12) ^ q(13) ^ q(14) ^ q(17) ^ q(20) ^ q(21) ^ q(23) ^ q(25) ^ q(26) ^ q(29) ^ d(0) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6) ^ d(9) ^ d(12) ^ d(13) ^ d(15) ^ d(17) ^ d(18) ^ d(21),
            q(9) ^ q(10) ^ q(11) ^ q(13) ^ q(14) ^ q(15) ^ q(18) ^ q(21) ^ q(22) ^ q(24) ^ q(26) ^ q(27) ^ q(30) ^ d(1) ^ d(2) ^ d(3) ^ d(5) ^ d(6) ^ d(7) ^ d(10) ^ d(13) ^ d(14) ^ d(16) ^ d(18) ^ d(19) ^ d(22),
            q(10) ^ q(11) ^ q(12) ^ q(14) ^ q(15) ^ q(16) ^ q(19) ^ q(22) ^ q(23) ^ q(25) ^ q(27) ^ q(28) ^ q(31) ^ d(2) ^ d(3) ^ d(4) ^ d(6) ^ d(7) ^ d(8) ^ d(11) ^ d(14) ^ d(15) ^ d(17) ^ d(19) ^ d(20) ^ d(23),
            q(11) ^ q(12) ^ q(13) ^ q(15) ^ q(16) ^ q(17) ^ q(20) ^ q(23) ^ q(24) ^ q(26) ^ q(28) ^ q(29) ^ d(3) ^ d(4) ^ d(5) ^ d(7) ^ d(8) ^ d(9) ^ d(12) ^ d(15) ^ d(16) ^ d(18) ^ d(20) ^ d(21),
            q(8) ^ q(12) ^ q(13) ^ q(16) ^ q(20) ^ q(21) ^ q(25) ^ q(27) ^ q(29) ^ q(30) ^ d(0) ^ d(4) ^ d(5) ^ d(8) ^ d(12) ^ d(13) ^ d(17) ^ d(19) ^ d(21) ^ d(22),
            q(9) ^ q(13) ^ q(14) ^ q(17) ^ q(21) ^ q(22) ^ q(26) ^ q(28) ^ q(30) ^ q(31) ^ d(1) ^ d(5) ^ d(6) ^ d(9) ^ d(13) ^ d(14) ^ d(18) ^ d(20) ^ d(22) ^ d(23),
            q(10) ^ q(14) ^ q(15) ^ q(18) ^ q(22) ^ q(23) ^ q(27) ^ q(29) ^ q(31) ^ d(2) ^ d(6) ^ d(7) ^ d(10) ^ d(14) ^ d(15) ^ d(19) ^ d(21) ^ d(23),
            q(11) ^ q(15) ^ q(16) ^ q(19) ^ q(23) ^ q(24) ^ q(28) ^ q(30) ^ d(3) ^ d(7) ^ d(8) ^ d(11) ^ d(15) ^ d(16) ^ d(20) ^ d(22),
            q(12) ^ q(16) ^ q(17) ^ q(20) ^ q(24) ^ q(25) ^ q(29) ^ q(31) ^ d(4) ^ d(8) ^ d(9) ^ d(12) ^ d(16) ^ d(17) ^ d(21) ^ d(23),
            q(13) ^ q(17) ^ q(18) ^ q(21) ^ q(25) ^ q(26) ^ q(30) ^ d(5) ^ d(9) ^ d(10) ^ d(13) ^ d(17) ^ d(18) ^ d(22),
            q(8) ^ q(17) ^ q(19) ^ q(20) ^ q(22) ^ q(24) ^ q(26) ^ q(27) ^ q(31) ^ d(0) ^ d(9) ^ d(11) ^ d(12) ^ d(14) ^ d(16) ^ d(18) ^ d(19) ^ d(23),
            q(8) ^ q(9) ^ q(14) ^ q(17) ^ q(21) ^ q(23) ^ q(24) ^ q(25) ^ q(27) ^ q(28) ^ d(0) ^ d(1) ^ d(6) ^ d(9) ^ d(13) ^ d(15) ^ d(16) ^ d(17) ^ d(19) ^ d(20),
            q(0) ^ q(9) ^ q(10) ^ q(15) ^ q(18) ^ q(22) ^ q(24) ^ q(25) ^ q(26) ^ q(28) ^ q(29) ^ d(1) ^ d(2) ^ d(7) ^ d(10) ^ d(14) ^ d(16) ^ d(17) ^ d(18) ^ d(20) ^ d(21),
            q(1) ^ q(10) ^ q(11) ^ q(16) ^ q(19) ^ q(23) ^ q(25) ^ q(26) ^ q(27) ^ q(29) ^ q(30) ^ d(2) ^ d(3) ^ d(8) ^ d(11) ^ d(15) ^ d(17) ^ d(18) ^ d(19) ^ d(21) ^ d(22),
            q(2) ^ q(8) ^ q(11) ^ q(12) ^ q(14) ^ q(18) ^ q(26) ^ q(27) ^ q(28) ^ q(30) ^ q(31) ^ d(0) ^ d(3) ^ d(4) ^ d(6) ^ d(10) ^ d(18) ^ d(19) ^ d(20) ^ d(22) ^ d(23),
            q(3) ^ q(9) ^ q(12) ^ q(13) ^ q(15) ^ q(19) ^ q(27) ^ q(28) ^ q(29) ^ q(31) ^ d(1) ^ d(4) ^ d(5) ^ d(7) ^ d(11) ^ d(19) ^ d(20) ^ d(21) ^ d(23),
            q(4) ^ q(10) ^ q(13) ^ q(14) ^ q(16) ^ q(20) ^ q(28) ^ q(29) ^ q(30) ^ d(2) ^ d(5) ^ d(6) ^ d(8) ^ d(12) ^ d(20) ^ d(21) ^ d(22),
            q(5) ^ q(11) ^ q(14) ^ q(15) ^ q(17) ^ q(21) ^ q(29) ^ q(30) ^ q(31) ^ d(3) ^ d(6) ^ d(7) ^ d(9) ^ d(13) ^ d(21) ^ d(22) ^ d(23),
            q(6) ^ q(12) ^ q(15) ^ q(16) ^ q(18) ^ q(22) ^ q(30) ^ q(31) ^ d(4) ^ d(7) ^ d(8) ^ d(10) ^ d(14) ^ d(22) ^ d(23),
            q(7) ^ q(13) ^ q(16) ^ q(17) ^ q(19) ^ q(23) ^ q(31) ^ d(5) ^ d(8) ^ d(9) ^ d(11) ^ d(15) ^ d(23),
        )


    def _generate_next_2B_crc(self, current_crc, data_in):
        """ Generates the next round of our CRC; given a 2B trailing input word . """

        # Helper functions that help us more clearly match the expanded polynomial form.
        d = lambda i : data_in[len(data_in) - i - 1]
        q = lambda i : current_crc[i]

        # These lines are extremely long, but there doesn't seem any advantage in clarity to splitting them.
        return Cat(
            q(16) ^ q(22) ^ q(25) ^ q(26) ^ q(28) ^ d(0) ^ d(6) ^ d(9) ^ d(10) ^ d(12),
            q(16) ^ q(17) ^ q(22) ^ q(23) ^ q(25) ^ q(27) ^ q(28) ^ q(29) ^ d(0) ^ d(1) ^ d(6) ^ d(7) ^ d(9) ^ d(11) ^ d(12) ^ d(13),
            q(16) ^ q(17) ^ q(18) ^ q(22) ^ q(23) ^ q(24) ^ q(25) ^ q(29) ^ q(30) ^ d(0) ^ d(1) ^ d(2) ^ d(6) ^ d(7) ^ d(8) ^ d(9) ^ d(13) ^ d(14),
            q(17) ^ q(18) ^ q(19) ^ q(23) ^ q(24) ^ q(25) ^ q(26) ^ q(30) ^ q(31) ^ d(1) ^ d(2) ^ d(3) ^ d(7) ^ d(8) ^ d(9) ^ d(10) ^ d(14) ^ d(15),
            q(16) ^ q(18) ^ q(19) ^ q(20) ^ q(22) ^ q(24) ^ q(27) ^ q(28) ^ q(31) ^ d(0) ^ d(2) ^ d(3) ^ d(4) ^ d(6) ^ d(8) ^ d(11) ^ d(12) ^ d(15),
            q(16) ^ q(17) ^ q(19) ^ q(20) ^ q(21) ^ q(22) ^ q(23) ^ q(26) ^ q(29) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(5) ^ d(6) ^ d(7) ^ d(10) ^ d(13),
            q(17) ^ q(18) ^ q(20) ^ q(21) ^ q(22) ^ q(23) ^ q(24) ^ q(27) ^ q(30) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6) ^ d(7) ^ d(8) ^ d(11) ^ d(14),
            q(16) ^ q(18) ^ q(19) ^ q(21) ^ q(23) ^ q(24) ^ q(26) ^ q(31) ^ d(0) ^ d(2) ^ d(3) ^ d(5) ^ d(7) ^ d(8) ^ d(10) ^ d(15),
            q(16) ^ q(17) ^ q(19) ^ q(20) ^ q(24) ^ q(26) ^ q(27) ^ q(28) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(8) ^ d(10) ^ d(11) ^ d(12),
            q(17) ^ q(18) ^ q(20) ^ q(21) ^ q(25) ^ q(27) ^ q(28) ^ q(29) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(9) ^ d(11) ^ d(12) ^ d(13),
            q(16) ^ q(18) ^ q(19) ^ q(21) ^ q(25) ^ q(29) ^ q(30) ^ d(0) ^ d(2) ^ d(3) ^ d(5) ^ d(9) ^ d(13) ^ d(14),
            q(16) ^ q(17) ^ q(19) ^ q(20) ^ q(25) ^ q(28) ^ q(30) ^ q(31) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(9) ^ d(12) ^ d(14) ^ d(15),
            q(16) ^ q(17) ^ q(18) ^ q(20) ^ q(21) ^ q(22) ^ q(25) ^ q(28) ^ q(29) ^ q(31) ^ d(0) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6) ^ d(9) ^ d(12) ^ d(13) ^ d(15),
            q(17) ^ q(18) ^ q(19) ^ q(21) ^ q(22) ^ q(23) ^ q(26) ^ q(29) ^ q(30) ^ d(1) ^ d(2) ^ d(3) ^ d(5) ^ d(6) ^ d(7) ^ d(10) ^ d(13) ^ d(14),
            q(18) ^ q(19) ^ q(20) ^ q(22) ^ q(23) ^ q(24) ^ q(27) ^ q(30) ^ q(31) ^ d(2) ^ d(3) ^ d(4) ^ d(6) ^ d(7) ^ d(8) ^ d(11) ^ d(14) ^ d(15),
            q(19) ^ q(20) ^ q(21) ^ q(23) ^ q(24) ^ q(25) ^ q(28) ^ q(31) ^ d(3) ^ d(4) ^ d(5) ^ d(7) ^ d(8) ^ d(9) ^ d(12) ^ d(15),
            q(0) ^ q(16) ^ q(20) ^ q(21) ^ q(24) ^ q(28) ^ q(29) ^ d(0) ^ d(4) ^ d(5) ^ d(8) ^ d(12) ^ d(13),
            q(1) ^ q(17) ^ q(21) ^ q(22) ^ q(25) ^ q(29) ^ q(30) ^ d(1) ^ d(5) ^ d(6) ^ d(9) ^ d(13) ^ d(14),
            q(2) ^ q(18) ^ q(22) ^ q(23) ^ q(26) ^ q(30) ^ q(31) ^ d(2) ^ d(6) ^ d(7) ^ d(10) ^ d(14) ^ d(15),
            q(3) ^ q(19) ^ q(23) ^ q(24) ^ q(27) ^ q(31) ^ d(3) ^ d(7) ^ d(8) ^ d(11) ^ d(15),
            q(4) ^ q(20) ^ q(24) ^ q(25) ^ q(28) ^ d(4) ^ d(8) ^ d(9) ^ d(12),
            q(5) ^ q(21) ^ q(25) ^ q(26) ^ q(29) ^ d(5) ^ d(9) ^ d(10) ^ d(13),
            q(6) ^ q(16) ^ q(25) ^ q(27) ^ q(28) ^ q(30) ^ d(0) ^ d(9) ^ d(11) ^ d(12) ^ d(14),
            q(7) ^ q(16) ^ q(17) ^ q(22) ^ q(25) ^ q(29) ^ q(31) ^ d(0) ^ d(1) ^ d(6) ^ d(9) ^ d(13) ^ d(15),
            q(8) ^ q(17) ^ q(18) ^ q(23) ^ q(26) ^ q(30) ^ d(1) ^ d(2) ^ d(7) ^ d(10) ^ d(14),
            q(9) ^ q(18) ^ q(19) ^ q(24) ^ q(27) ^ q(31) ^ d(2) ^ d(3) ^ d(8) ^ d(11) ^ d(15),
            q(10) ^ q(16) ^ q(19) ^ q(20) ^ q(22) ^ q(26) ^ d(0) ^ d(3) ^ d(4) ^ d(6) ^ d(10),
            q(11) ^ q(17) ^ q(20) ^ q(21) ^ q(23) ^ q(27) ^ d(1) ^ d(4) ^ d(5) ^ d(7) ^ d(11),
            q(12) ^ q(18) ^ q(21) ^ q(22) ^ q(24) ^ q(28) ^ d(2) ^ d(5) ^ d(6) ^ d(8) ^ d(12),
            q(13) ^ q(19) ^ q(22) ^ q(23) ^ q(25) ^ q(29) ^ d(3) ^ d(6) ^ d(7) ^ d(9) ^ d(13),
            q(14) ^ q(20) ^ q(23) ^ q(24) ^ q(26) ^ q(30) ^ d(4) ^ d(7) ^ d(8) ^ d(10) ^ d(14),
            q(15) ^ q(21) ^ q(24) ^ q(25) ^ q(27) ^ q(31) ^ d(5) ^ d(8) ^ d(9) ^ d(11) ^ d(15),
        )


    def _generate_next_1B_crc(self, current_crc, data_in):
        """ Generates the next round of our CRC; given a 2B trailing input word . """

        # Helper functions that help us more clearly match the expanded polynomial form.
        d = lambda i : data_in[len(data_in) - i - 1]
        q = lambda i : current_crc[i]

        return Cat(
            q(24) ^ q(30) ^ d(0) ^ d(6),
            q(24) ^ q(25) ^ q(30) ^ q(31) ^ d(0) ^ d(1) ^ d(6) ^ d(7),
            q(24) ^ q(25) ^ q(26) ^ q(30) ^ q(31) ^ d(0) ^ d(1) ^ d(2) ^ d(6) ^ d(7),
            q(25) ^ q(26) ^ q(27) ^ q(31) ^ d(1) ^ d(2) ^ d(3) ^ d(7),
            q(24) ^ q(26) ^ q(27) ^ q(28) ^ q(30) ^ d(0) ^ d(2) ^ d(3) ^ d(4) ^ d(6),
            q(24) ^ q(25) ^ q(27) ^ q(28) ^ q(29) ^ q(30) ^ q(31) ^ d(0) ^ d(1) ^ d(3) ^ d(4) ^ d(5) ^ d(6) ^ d(7),
            q(25) ^ q(26) ^ q(28) ^ q(29) ^ q(30) ^ q(31) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6) ^ d(7),
            q(24) ^ q(26) ^ q(27) ^ q(29) ^ q(31) ^ d(0) ^ d(2) ^ d(3) ^ d(5) ^ d(7),
            q(0) ^ q(24) ^ q(25) ^ q(27) ^ q(28) ^ d(0) ^ d(1) ^ d(3) ^ d(4),
            q(1) ^ q(25) ^ q(26) ^ q(28) ^ q(29) ^ d(1) ^ d(2) ^ d(4) ^ d(5),
            q(2) ^ q(24) ^ q(26) ^ q(27) ^ q(29) ^ d(0) ^ d(2) ^ d(3) ^ d(5),
            q(3) ^ q(24) ^ q(25) ^ q(27) ^ q(28) ^ d(0) ^ d(1) ^ d(3) ^ d(4),
            q(4) ^ q(24) ^ q(25) ^ q(26) ^ q(28) ^ q(29) ^ q(30) ^ d(0) ^ d(1) ^ d(2) ^ d(4) ^ d(5) ^ d(6),
            q(5) ^ q(25) ^ q(26) ^ q(27) ^ q(29) ^ q(30) ^ q(31) ^ d(1) ^ d(2) ^ d(3) ^ d(5) ^ d(6) ^ d(7),
            q(6) ^ q(26) ^ q(27) ^ q(28) ^ q(30) ^ q(31) ^ d(2) ^ d(3) ^ d(4) ^ d(6) ^ d(7),
            q(7) ^ q(27) ^ q(28) ^ q(29) ^ q(31) ^ d(3) ^ d(4) ^ d(5) ^ d(7),
            q(8) ^ q(24) ^ q(28) ^ q(29) ^ d(0) ^ d(4) ^ d(5),
            q(9) ^ q(25) ^ q(29) ^ q(30) ^ d(1) ^ d(5) ^ d(6),
            q(10) ^ q(26) ^ q(30) ^ q(31) ^ d(2) ^ d(6) ^ d(7),
            q(11) ^ q(27) ^ q(31) ^ d(3) ^ d(7),
            q(12) ^ q(28) ^ d(4),
            q(13) ^ q(29) ^ d(5),
            q(14) ^ q(24) ^ d(0),
            q(15) ^ q(24) ^ q(25) ^ q(30) ^ d(0) ^ d(1) ^ d(6),
            q(16) ^ q(25) ^ q(26) ^ q(31) ^ d(1) ^ d(2) ^ d(7),
            q(17) ^ q(26) ^ q(27) ^ d(2) ^ d(3),
            q(18) ^ q(24) ^ q(27) ^ q(28) ^ q(30) ^ d(0) ^ d(3) ^ d(4) ^ d(6),
            q(19) ^ q(25) ^ q(28) ^ q(29) ^ q(31) ^ d(1) ^ d(4) ^ d(5) ^ d(7),
            q(20) ^ q(26) ^ q(29) ^ q(30) ^ d(2) ^ d(5) ^ d(6),
            q(21) ^ q(27) ^ q(30) ^ q(31) ^ d(3) ^ d(6) ^ d(7),
            q(22) ^ q(28) ^ q(31) ^ d(4) ^ d(7),
            q(23) ^ q(29) ^ d(5),
        )


    def elaborate(self, platform):
        m = Module()

        # Register that contains the running CRCs.
        crc         = Signal(32, reset=self._initial_value)

        # Internal signals representing our next internal state given various input sizes.
        next_crc_3B = Signal.like(crc)
        next_crc_2B = Signal.like(crc)
        next_crc_1B = Signal.like(crc)

        # Compute each of our theoretical partial "next-CRC" values.
        m.d.comb += [
            next_crc_3B.eq(self._generate_next_3B_crc(crc, self.data_input[0:24])),
            next_crc_2B.eq(self._generate_next_2B_crc(crc, self.data_input[0:16])),
            next_crc_1B.eq(self._generate_next_1B_crc(crc, self.data_input[0:8])),
        ]

        # If we're clearing our CRC in progress, move our holding register back to
        # our initial value.
        with m.If(self.clear):
            m.d.ss += crc.eq(self._initial_value)

        # Otherwise, update the CRC whenever we have new data.
        with m.Elif(self.advance_word):
            m.d.ss   += crc.eq(self._generate_next_full_crc(crc, self.data_input))
        with m.Elif(self.advance_3B):
            m.d.ss   += crc.eq(next_crc_3B)
        with m.Elif(self.advance_2B):
            m.d.ss   += crc.eq(next_crc_2B)
        with m.Elif(self.advance_1B):
            m.d.ss   += crc.eq(next_crc_1B)


        # Convert from our intermediary "running CRC" format into the correct CRC32 outputs.
        m.d.comb += [
            self.crc          .eq(~crc[::-1]),
            self.next_crc_3B  .eq(~next_crc_3B[::-1]),
            self.next_crc_2B  .eq(~next_crc_2B[::-1]),
            self.next_crc_1B  .eq(~next_crc_1B[::-1])
        ]

        return m


class DataPacketPayloadCRCTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = DataPacketPayloadCRC

    @ss_domain_test_case
    def test_aligned_crc(self):
        dut = self.dut

        #yield dut.advance_word.eq(1)

        for i in (0x02000112, 0x40000000):
            yield dut.data_input.eq(i)
            yield from self.pulse(dut.advance_word, step_after=False)

        self.assertEqual((yield dut.crc), 0x34984B13)


    @ss_domain_test_case
    def test_unaligned_crc(self):
        dut = self.dut


        # Aligned section of a real USB data capture, from a USB flash drive.
        aligned_section =[
            0x03000112,
            0x09000000,
            0x520013FE,
            0x02010100,
        ]

        # Present the aligned section...
        for i in aligned_section:
            yield dut.data_input.eq(i)
            yield from self.pulse(dut.advance_word, step_after=False)

        # ... and then our unaligned data.
        yield dut.data_input.eq(0x0000_0103)
        yield

        # Our next-CRC should indicate the correct value...
        self.assertEqual((yield dut.next_crc_2B), 0x540aa487)

        # ...and after advancing, we should see the same value on our CRC output.
        yield from self.pulse(dut.advance_2B)
        self.assertEqual((yield dut.crc), 0x540aa487)


if __name__ == "__main__":
    unittest.main()
