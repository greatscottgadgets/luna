#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" CRC computation gateware for USB3. """

from nmigen import *

import functools
import operator



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
        """ Generates the next round of a bytewise USB CRC16. """

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
