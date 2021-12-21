#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Data header handling gateware.

This file currently contains very little logic; the actual transmission framing is handled at
the link layer; and the generation of our packets is handled by our endpoint.

"""

from amaranth import *
from usb_protocol.types.superspeed import HeaderPacketType

from ..link.header import HeaderQueue
from ..link.data   import DataHeaderPacket
from ...stream     import SuperSpeedStreamInterface
from ...request    import SetupPacket


class DataHeaderReceiver(Elaboratable):
    """ Gateware that handles received Data Header packets.

    Attributes
    -----------
    header_sink: HeaderQueue(), input stream
        Stream that brings up header packets for handling.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.header_sink   = HeaderQueue()


    def elaborate(self, platform):
        m = Module()

        # We handle Data Packets specially, passing their header data in conjunction with
        # the packets themselves; but the header packets are still handled like other header
        # packets, and must be explicitly consumed by the protocol layer.
        #
        # We'll consume all of them here, since we don't have any direct use for their data.
        new_packet = self.header_sink.valid
        is_for_us  = self.header_sink.get_type() == HeaderPacketType.DATA
        with m.If(new_packet & is_for_us):
            m.d.comb += self.header_sink.ready.eq(1)

        return m


