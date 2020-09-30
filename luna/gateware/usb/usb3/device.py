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
from .physical import USB3PhysicalLayer
from .link     import USB3LinkLayer

# Temporary
from ..stream  import USBRawSuperSpeedStream


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
        self.link_trained = Signal()

        # Temporary, debug signals.
        self.rx_data_tap         = USBRawSuperSpeedStream()
        self.tx_data_tap         = USBRawSuperSpeedStream()


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
            self.link_trained     .eq(link.trained)
        ]


        #
        # Protocol layer.
        #
        # TODO

        #
        # Application layer.
        #
        # TODO

        #
        # Debug helpers.
        #

        # Tap our transmit and receive lines, so they can be externally analyzed.
        m.d.comb += [
            self.rx_data_tap  .stream_eq(physical.source, omit={'ready'}),
            self.tx_data_tap  .stream_eq(physical.sink,   omit={'ready'})
        ]


        return m
