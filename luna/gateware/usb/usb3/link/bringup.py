#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Gateware for USB3 link bringup. """

from nmigen         import *
from nmigen.hdl.ast import Past

from ...stream import USBRawSuperSpeedStream

from .command import LinkCommand


class LinkBringupSequencer(Elaboratable):
    """ Module that sequences the events necessary to bring up our link once we enter U0.

    This module mainly orchestrates three tasks:
        - the initial LGOOD_n advertisement,
        - header credit initialization, and
        - port initialization.

    Attributes
    ----------
    entering_u0: Signal(), input
        Strobe; indicates that we've freshly entered u0.

    """

    HEADER_BUFFERS_AVAILABLE     = 4
    FIRST_SEQUENCE_ADVERTISEMENT = 7

    def __init__(self):

        #
        # I/O port
        #
        self.entering_u0          = Signal()

        # Link command interfacing.
        self.request_link_command = Signal()
        self.link_command         = Signal(4)
        self.link_command_subtype = Signal(4)
        self.link_command_done    = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Core orchestration FSM.
        #
        with m.FSM(domain="ss"):

            # IDLE -- we're waiting for the system to transition into U0; either we've not
            # yet entered U0 or the link has already been brought up.
            with m.State("IDLE"):

                with m.If(self.entering_u0):
                    m.next = "LGOOD_ADVERTISEMENT"


            # LGOOD_ADVERTISEMENT -- we'll start off link bringup by advertising our header
            # sequence number, which should start off at 0. [USB3.2r1: 7.2.4.1.1]
            with m.State("LGOOD_ADVERTISEMENT"):

                # We'll start off by advertising that our sequence will start at zero.
                # Per [USB3.2r1: 7.2.4.1.1], we do this by sending an LGOOD command with
                # a subtype of one less than our first header number; which for Gen1 speeds
                # wraps around to 7.
                m.d.comb += [
                    self.request_link_command  .eq(1),
                    self.link_command          .eq(LinkCommand.LGOOD),
                    self.link_command_subtype  .eq(7)
                ]

                # Wait until our link command is done, and then move on.
                with m.If(self.link_command_done):
                    m.d.comb += self.request_link_command.eq(0)
                    m.next = "LCRD_ADVERTISEMENT_0"


            # LCRD_ADVERTISEMENT_n -- we'll advertise to the host that each of our
            # header buffers is available, so we can start receiving header packets.
            #
            # We'll generate a state to set up each of our buffers.
            for buffer in range(self.HEADER_BUFFERS_AVAILABLE):
                with m.State(f"LCRD_ADVERTISEMENT_{buffer}"):

                    # Indicate that the relevant buffer is available...
                    m.d.comb += [
                        self.request_link_command  .eq(1),
                        self.link_command          .eq(LinkCommand.LCRD),
                        self.link_command_subtype  .eq(buffer)
                    ]

                    # ... and then move on to the next buffer.
                    with m.If(self.link_command_done):
                        m.d.comb += self.request_link_command.eq(0)

                        # If this isn't our last buffer, move to the next advertisement.
                        if (buffer + 1) < self.HEADER_BUFFERS_AVAILABLE:
                            m.next = f"LCRD_ADVERTISEMENT_{buffer + 1}"

                        # Otherwise, move on to our LMP handshake.
                        else:
                            m.next = "ISSUE_LMP"


            # ISSUE_LMP -- we'll now issue our Port Capability advertisement Link Management
            # Packet (LMP), which communicates our basic link parameters.
            with m.State("LGOOD_ADVERTISEMENT"):

                # TODO: implement this
                pass

        return m
