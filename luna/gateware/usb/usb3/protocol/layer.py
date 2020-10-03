#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from nmigen import *

from .link_management import LinkManagementPacketHandler
from ...stream        import USBRawSuperSpeedStream


class USB3ProtocolLayer(Elaboratable):
    """ Abstraction encapsulating the USB3 protocol layer hardware. """

    def __init__(self, *, link_layer):
        self._link = link_layer


    def elaborate(self, platform):
        m = Module()
        link = self._link

        #
        # Link Management Packet Handler
        #
        m.submodules.lmp_handler = lmp_handler = LinkManagementPacketHandler()
        m.d.comb += [
            lmp_handler.link_ready    .eq(link.trained),

            lmp_handler.header_sink   .header_eq(link.header_source),
            link.header_sink          .header_eq(lmp_handler.header_source),
        ]

        return m
