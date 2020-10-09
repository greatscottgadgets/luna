#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
"""
Contains the organizing hardware used to add USB3 Device functionality
to your own designs; including the core :class:`USBSuperSpeedDevice` class.
"""

import logging

from nmigen import *

# USB3 Protocol Stack
from .physical  import USB3PhysicalLayer
from .link      import USB3LinkLayer
from .protocol  import USB3ProtocolLayer
from .endpoints import USB3ControlEndpoint

# Temporary
from ..stream  import USBRawSuperSpeedStream, SuperSpeedStreamInterface


class USBSuperSpeedDevice(Elaboratable):
    """ Core gateware common to all LUNA USB3 devices. """

    def __init__(self, *, phy, sync_frequency):
        self._phy = phy
        self._sync_frequency = sync_frequency

        # TODO: remove when complete
        logging.warning("USB3 device support is not at all complete!")
        logging.warning("Do not expect -anything- to work!")

        #
        # I/O port
        #

        # General status signals.
        self.link_trained   = Signal()
        self.link_in_reset  = Signal()

        # Temporary, debug signals.
        self.rx_data_tap         = USBRawSuperSpeedStream()
        self.tx_data_tap         = USBRawSuperSpeedStream()

        self.ep_rx_stream        = SuperSpeedStreamInterface()
        self.is_setup            = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Physical layer.
        #
        m.submodules.physical = physical = USB3PhysicalLayer(
            phy            = self._phy,
            sync_frequency = self._sync_frequency
        )

        #
        # Link layer.
        #
        m.submodules.link = link = USB3LinkLayer(physical_layer=physical)
        m.d.comb += [
            self.link_trained     .eq(link.trained),
            self.link_in_reset    .eq(link.in_reset)
        ]

        #
        # Protocol layer.
        #
        m.submodules.protocol = protocol = USB3ProtocolLayer(link_layer=link)


        #
        # Application layer.
        #

        # TODO: build a collection of endpoint interfaces, and arbitrate between them
        # FIXME: remove this scaffolding, and replace it with a real interface.
        m.submodules.control_ep = control_ep = USB3ControlEndpoint()
        m.d.comb += [
            control_ep.interface.rx                     .tap(protocol.endpoint_interface.rx),
            control_ep.interface.rx_header              .eq(protocol.endpoint_interface.rx_header),
            control_ep.interface.rx_complete            .eq(protocol.endpoint_interface.rx_complete),
            control_ep.interface.rx_invalid             .eq(protocol.endpoint_interface.rx_invalid),

            protocol.endpoint_interface.handshakes_out  .connect(control_ep.interface.handshakes_out),
            protocol.endpoint_interface.handshakes_in   .connect(control_ep.interface.handshakes_in)
        ]



        #
        # Debug helpers.
        #

        # Tap our transmit and receive lines, so they can be externally analyzed.
        m.d.comb += [
            self.rx_data_tap   .tap(physical.source),
            self.tx_data_tap   .tap(physical.sink),

            self.ep_rx_stream  .tap(protocol.endpoint_interface.rx),
            self.is_setup      .eq(protocol.endpoint_interface.rx_header.setup)
        ]


        return m
