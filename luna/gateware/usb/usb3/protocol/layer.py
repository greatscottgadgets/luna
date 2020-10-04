#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from nmigen import *

from ..link.header    import HeaderQueueDemultiplexer
from ...stream        import USBRawSuperSpeedStream

from .link_management import LinkManagementPacketHandler
from .timestamp       import TimestampPacketReceiver


class USB3ProtocolLayer(Elaboratable):
    """ Abstraction encapsulating the USB3 protocol layer hardware. """

    def __init__(self, *, link_layer):
        self._link = link_layer

        #
        # I/O port
        #
        self.bus_interval = Signal(14)


    def elaborate(self, platform):
        m = Module()
        link = self._link

        #
        # Header Packet Multiplexers
        #

        # One-to-many Header demultiplexer.
        m.submodules.hp_demux = hp_demux = HeaderQueueDemultiplexer()
        m.d.comb += hp_demux.sink.header_eq(link.header_source)


        #
        # Link Management Packet Handler
        #
        m.submodules.lmp_handler = lmp_handler = LinkManagementPacketHandler()
        hp_demux.add_consumer(lmp_handler.header_sink)

        m.d.comb += [
            lmp_handler.link_ready    .eq(link.ready),
            link.header_sink          .header_eq(lmp_handler.header_source),
        ]

        #
        # Isochronous Timestamp Packet Handler
        #
        m.submodules.itp_handler = itp_handler = TimestampPacketReceiver()
        hp_demux.add_consumer(itp_handler.header_sink)

        m.d.comb += [
            self.bus_interval.eq(itp_handler.bus_interval_counter)
        ]




        return m
