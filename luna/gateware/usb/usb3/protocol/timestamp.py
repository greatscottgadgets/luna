#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Isochronous Timestamp Packet (ITP)-related gateware. """

from amaranth import *
from usb_protocol.types.superspeed import HeaderPacketType

from ..link.header import HeaderQueue, HeaderPacket


class TimestampPacketReceiver(Elaboratable):
    """ Gateware that receives Isochronous Timestamp Packets, and keeps time.

    Attributes
    ----------
    header_sink: HeaderQueue(), input stream
        Input stream carrying header packets from the link layer.

    bus_interval_counter: Signal(14), output
        The currently timestamp, expressed in a number of 125uS bus intervals.
    delta: Signal(13)
        The delta from the aligned bus interval and ITP transmission.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.header_sink          = HeaderQueue()

        self.update_received      = Signal()
        self.bus_interval_counter = Signal()
        self.delta                = Signal()


    def elaborate(self, platform):
        m = Module()

        # Accept any Isochronous Timestamp Packet...
        new_packet = self.header_sink.valid
        is_for_us  = self.header_sink.get_type() == HeaderPacketType.ISOCHRONOUS_TIMESTAMP
        with m.If(new_packet & is_for_us):
            m.d.comb += self.header_sink.ready.eq(1)

            # ... and extract its fields.
            packet = self.header_sink.header
            m.d.ss += [
                self.update_received       .eq(1),
                self.bus_interval_counter  .eq(packet.dw0[ 5:19]),
                self.delta                 .eq(packet.dw0[19:32])
            ]
        with m.Else():
            m.d.ss += self.update_received.eq(0)

        return m
