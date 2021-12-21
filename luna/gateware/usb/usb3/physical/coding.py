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

def K(x, y):
    """ Converts K/control codes to bytes

    Does not result in 8b10b data; requires explicit encoding.
    See the USB3 / PCIe specifications for more information.
    """
    return (y << 5) | x

def D(x, y):
    """ Converts D/data codes to bytes.

    Does not result in 8b10b data; requires explicit encoding.
    See the USB3 / PCIe specifications for more information.
    """
    return (y << 5) | x


class NamedSymbol:
    """ Simple encapsulation of a USB3 symbol, with simple metadata. """

    def __init__(self, name, value, description="", is_data=False):
        self.name        = name
        self.value       = value
        self.description = description
        self.ctrl        = 0 if is_data else 1

    def value_const(self, *, repeat=1):
        """ Returns this symbol's data value as an Amaranth const. """
        value = Const(self.value, 8)
        return Repl(value, repeat)


    def ctrl_const(self, *, repeat=1):
        """ Returns this symbol's ctrl value as an Amaranth const. """
        ctrl =  Const(self.ctrl, 1)
        return Repl(ctrl, repeat)


SKP =  NamedSymbol("SKP", K(28, 1), "Skip")                              # 3c
SDP =  NamedSymbol("SDP", K(28, 2), "Start Data Packet")                 # 5c
EDB =  NamedSymbol("EDB", K(28, 3), "End Bad")                           # 7c
SUB =  NamedSymbol("SUB", K(28, 4), "Decode Error Substitution")         # 9c
COM =  NamedSymbol("COM", K(28, 5), "Comma")                             # bc
RSD =  NamedSymbol("RSD", K(28, 6), "Reserved")                          # dc
SHP =  NamedSymbol("SHP", K(27, 7), "Start Header Packet")               # fb
END =  NamedSymbol("END", K(29, 7), "End")                               # fd
SLC =  NamedSymbol("SLC", K(30, 7), "Start Link Command")                # fe
EPF =  NamedSymbol("EPF", K(23, 7), "End Packet Framing")                # f7
IDL =  NamedSymbol("IDL", D(0, 0),  "Logical Idle", is_data=True)        # 00

symbols = [SKP, SDP, EDB, SUB, COM, RSD, SHP, END, SLC, EPF]


def get_word_for_symbols(*target_symbols):
    """ Returns a pair of Amaranth constants containing the data and ctrl values for the given symbols. """

    # Create constants that match the target data/ctrl bits for the given set of symbols.
    target_data = Cat(symbol.value_const() for symbol in target_symbols)
    target_ctrl = Cat(symbol.ctrl_const() for  symbol in target_symbols)

    return target_data, target_ctrl


def stream_matches_symbols(stream, *target_symbols, include_ready=False):
    """ Returns an Amaranth conditional that evaluates true when a stream contains the given four symbols.

    Notes:
        - The given conditional evaluates to False when ``stream.valid`` is falsey.
        - Assumes the stream is little endian, so the bytes of the stream would read SYM3 SYM2 SYM1 SYM0.
    """

    target_data, target_ctrl = get_word_for_symbols(*target_symbols)
    stream_ready = stream.ready if include_ready else True

    return (
        stream.valid & stream_ready  &
        (stream.data == target_data) &
        (stream.ctrl == target_ctrl)
    )


def stream_word_matches_symbol(stream, word_number, *, symbol):
    """ Returns an Amaranth conditional that evaluates true if the given word of a stream matches the given symbol. """

    return (
        stream.valid &
        (stream.data.word_select(word_number, 8) == symbol.value) &
        (stream.ctrl[word_number] == symbol.ctrl)
    )

