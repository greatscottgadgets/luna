#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Link Management Packet (LMP) -related gateware. """

from nmigen import *
from usb_protocol.types.superspeed import HeaderPacketType, LinkManagementPacketSubtype

from ..link.header import HeaderQueue


class LinkManagementPacketHandler(Elaboratable):
    """ Gateware that handles Link Management Packets. """

    def __init__(self):

        #
        # I/O port
        #
        self.header_sink   = HeaderQueue()
        self.header_source = HeaderQueue()

        # Status / control.
        self.link_ready    = Signal()


    def elaborate(self, platform):
        m = Module()

        header_sink   = self.header_sink
        header_source = self.header_source

        header_out    = self.header_source.header

        #
        # LMP transmitter.
        #

        with m.FSM(domain="ss"):

            # LINK_DOWN -- our link is not yet ready to exchange packets; we'll wait until
            # it's come up to the point where we can exchange header packets.
            with m.State("LINK_DOWN"):

                # Once our link is ready, we're ready to start link bringup.
                with m.If(self.link_ready):
                    m.next = "SEND_CAPABILITIES"


            # SEND_CAPABILITIES -- our link has come up; and we're now ready to advertise our link
            # capabilities to the other side of our link [USB3.2r1: 8.4.5].
            with m.State("SEND_CAPABILITIES"):
                m.d.comb += [
                    # Mark ourselves as sending a packet...
                    header_source.valid  .eq(1),

                    # ... with a type of LMP PORT CAPABILITY.
                    header_out.dw0[0:5]  .eq(HeaderPacketType.LINK_MANAGEMENT),
                    header_out.dw0[5:9]  .eq(LinkManagementPacketSubtype.PORT_CAPABILITY),

                    # We only support Gen1 / 5Gbps operation, so just set bit 9 of the remainder of DW0.
                    header_out.dw0[9]    .eq(1),

                    # Next, we should advertise how many buffers we have for header packets.
                    # By specification, this must be 4 for Gen1 devices.
                    header_out.dw1[0:8]  .eq(4),

                    # We currently only support being an upstream facing device, so we only set DW1[16].
                    header_out.dw1[17]   .eq(1)
                ]

                # Once the link layer accepts this packet, we're done!
                with m.If(header_source.ready):
                    m.next = "DISPATCH_COMMANDS"


            with m.State("DISPATCH_COMMANDS"):
                pass


        #
        # LMP receiver.
        #

        # FIXME: implement this
        # For now, as a placeholder, black-hole all received Link Management packets.
        with m.If(header_sink.get_type() == HeaderPacketType.LINK_MANAGEMENT):
            m.d.comb += header_sink.ready.eq(1)


        return m
