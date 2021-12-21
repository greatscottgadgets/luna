#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Request components shared between USB2 and USB3. """

from amaranth       import *
from amaranth.hdl.rec import DIR_FANOUT


class SetupPacket(Record):
    """ Record capturing the content of a setup packet.

    Components (O = output from setup parser; read-only input to others):
        O: received      -- Strobe; indicates that a new setup packet has been received,
                            and thus this data has been updated.

        O: is_in_request -- High if the current request is an 'in' request.
        O: type[2]       -- Request type for the current request.
        O: recipient[5]  -- Recipient of the relevant request.

        O: request[8]    -- Request number.
        O: value[16]     -- Value argument for the setup request.
        O: index[16]     -- Index argument for the setup request.
        O: length[16]    -- Length of the relevant setup request.
    """

    def __init__(self):
        super().__init__([
            # Byte 1
            ('recipient',      5, DIR_FANOUT),
            ('type',           2, DIR_FANOUT),
            ('is_in_request',  1, DIR_FANOUT),

            # Byte 2
            ('request',        8, DIR_FANOUT),

            # Byte 3/4
            ('value',         16, DIR_FANOUT),

            # Byte 5/6
            ('index',         16, DIR_FANOUT),

            # Byte 7/8
            ('length',        16, DIR_FANOUT),

            # Control signaling.
            ('received',       1, DIR_FANOUT),
        ])

