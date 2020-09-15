#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code adapted from ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Code for USB3 physical-layer encoding. """

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

    def __init__(self, name, value, description=""):
        self.name        = name
        self.value       = value
        self.description = description

SKP =  NamedSymbol("SKP", K(28, 1), "Skip")
SDP =  NamedSymbol("SDP", K(28, 2), "Start Data Packet")
EDB =  NamedSymbol("EDB", K(28, 3), "End Bad")
SUB =  NamedSymbol("SUB", K(28, 4), "Decode Error Substitution")
COM =  NamedSymbol("COM", K(28, 5), "Comma")
RSD =  NamedSymbol("RSD", K(28, 6), "Reserved")
SHP =  NamedSymbol("SHP", K(27, 7), "Start Header Packet")
END =  NamedSymbol("END", K(29, 7), "End")
SLC =  NamedSymbol("SLC", K(30, 7), "Start Link Command")
EPF =  NamedSymbol("EPF", K(23, 7), "End Packet Framing")
IDL =  NamedSymbol("IDL", D(0, 0),  "Logical Idle")

symbols = [SKP, SDP, EDB, SUB, COM, RSD, SHP, END, SLC, EPF]
