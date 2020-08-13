#
# This file is part of LUNA
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" ECP5 configuration code for LUNA. """

import time

from enum import IntEnum
from collections import defaultdict

from .jtag import JTAGChain
from .support.bits import bits


class IntelJTAGProgrammer:
    """ Apollo JTAG configuration tool for Intel FPGAs.

    Parameters
    ----------
    jtag_chain: JTAGChain
        The JTAG chain to be used for configuration.
    """

    def __init__(self, jtag_chain, *args, **kwargs):

        # Store a reference to our board and SPI bus.
        self.chain = jtag_chain


    def _generate_bit_reversed_bitstream(self, bitstream):
        """
        Generates a copy of the provided bitstream with the bits in each byte
        reversed -- in the format the FPGA likes them for MSPI mode.
        """

        # Quick helper function to reverse the bits in our bitstream.
        def reverse_bits(num):
            binstr = "{:08b}".format(num)
            return int(binstr[::-1], 2)

        # Reverse each of the bits in each byte of the bitstream.
        #
        # This ensures that bits are shifted into the FPGA in the same
        # order as they need to be presented to the configuration logic;
        # even if the FPGA is the one commanding the flash.
        #
        bit_reversed = bytearray(bitstream)
        for i in range(len(bit_reversed)):
            bit_reversed[i] = reverse_bits(bit_reversed[i])

        return bit_reversed



    def configure(self, bitstream):
        """ Configures the FPGA. """

        bitstream_length_bits = len(bitstream) * 8

        # The actual JTAG commands for loading bitstreams are not clearly documented;
        # these values were found by copying the least collection of instructions that
        # seemed to result in a reliable configuration from a Quartus-generated SVF,
        # and correlating with CYIV-51008, which references some instruction ordering
        # and names without additional documentation.
        #
        # These could be very wrong.
        #
        IR_LENGTH         = 10
        JTAG_PROGRAM      = 0x002
        JTAG_STARTUP      = 0x003

        # Upload our bitstream to our board ...
        self.chain.shift_instruction(JTAG_PROGRAM, length=IR_LENGTH, state_after='IRPAUSE')
        self.chain.shift_data(tdi=bitstream, length=bitstream_length_bits,
            ignore_response=True, state_after='IDLE', byteorder='little')

        # ... and apply it / let it start.
        self.chain.shift_instruction(JTAG_STARTUP, length=IR_LENGTH, state_after='IRPAUSE')
        self.chain.run_test(102400)

