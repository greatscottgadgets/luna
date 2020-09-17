#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB Link Commands Transmitter/Receivers """

import functools
import operator

from nmigen         import *
from nmigen.hdl.ast import Past

from ..physical.coding import SLC, EPF, stream_matches_symbols

from ...stream import USBRawSuperSpeedStream


def _generate_crc_for_link_command(token):
    """ Generates a 5-bit signal equivalent to the CRC check for given 11 bits of Link Command Information. """

    def xor_bits(*indices):
        bits = (token[len(token) - 1 - i] for i in indices)
        return functools.reduce(operator.__xor__, bits)

    # Implements the CRC polynomial from the USB specification.
    return Cat(
            xor_bits(10, 9, 8, 5, 4, 2),
           ~xor_bits(10, 9, 8, 7, 4, 3, 1),
            xor_bits(10, 9, 8, 7, 6, 3, 2, 0),
            xor_bits(10, 7, 6, 4, 1),
            xor_bits(10, 9, 6, 5, 3, 0)
    )


class LinkCommandDetector(Elaboratable):
    """ USB3 Link Command Detector.

    This module detects USB3 link commands as they're received on the bus.

    Attributes
    ----------
    sink: USBRawSuperSpeedStream, input stream
        The (aligned and descrambled) data stream captured from the physical layer.

    command: Signal(4), output
        The link command; including its two-bit class and two-bit type.

    command_class: Signal(2), output
        The link command's class; equivalent to the first two bits of :attr:``command``.
    command_type: Signal(2), output
        The link command's type; equivalent to the second two bits of :attr:``command``.

    subtype: Signal(4), output
        The link command's subtype.

    new_command: signal(), output
        Strobe; indicates that a new link command has been received, and the details of this command
        are ready to be read.


    """

    def __init__(self):

        #
        # I/O port
        #
        self.sink = USBRawSuperSpeedStream()

        # Link command information.
        self.command       = Signal(4)
        self.command_class = Signal(2)
        self.command_type  = Signal(2)
        self.subtype       = Signal(4)

        # Status strobes.
        self.new_command   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Create our ``command_class`` and ``command_type`` aliases,
        # which are always just slices of our command.
        m.d.comb += [
            self.command_class  .eq(self.command[2:4]),
            self.command_type   .eq(self.command[0:2])
        ]

        # Assume we don't have a new command, unless asserted below.
        m.d.ss += self.new_command.eq(0)

        with m.FSM(domain="ss"):

            # WAIT_FOR_LCSTART -- we're currently waiting for LCSTART framing, which indicates
            # that the following word is a link command.
            with m.State("WAIT_FOR_LCSTART"):

                is_lcstart = stream_matches_symbols(self.sink, SLC, SLC, SLC, EPF)
                with m.If(is_lcstart):
                    m.next = "PARSE_COMMAND"


            # PARSE_COMMAND -- our previous data word contained LCSTART; so this word contains our
            # link command. We'll parse / validate it.
            with m.State("PARSE_COMMAND"):

                with m.If(self.sink.valid):

                    link_command_word    = self.sink.data.word_select(0, 16)
                    link_command_replica = self.sink.data.word_select(1, 16)

                    # The payload of a link command contains only data packets; and should never contain
                    # control packets. We'll sanity check this.
                    contains_only_data = (self.sink.ctrl == 0)

                    # A valid two-byte link command word is repeated twice, exactly. [USB3.2r1: 7.2.2.1]
                    # Per the specification, we can only accept commands where both copies match.
                    redundancy_matches = (link_command_word == link_command_replica)

                    # The core ten bits of our link command word are guarded by a CRC-5. We'll only
                    # accept link commands whose CRC matches.
                    # FIXME: do this
                    crc_matches = 1

                    # If we have a word that matches -all- of these criteria, accept it as a new command.
                    with m.If(contains_only_data & redundancy_matches & crc_matches):
                        m.d.ss += [

                            # Copy our fields out of the link command...
                            self.command      .eq(link_command_word[7:11]),
                            self.subtype      .eq(link_command_word[0: 4]),

                            # ... and indicate that we've received a new command
                            self.new_command  .eq(1)

                        ]

                    # No matter the word's validity, we'll move back to waiting for a new command header;
                    # as we can't do anything about invalid commands.
                    m.next = "WAIT_FOR_LCSTART"


        return m
