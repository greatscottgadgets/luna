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

    def __init__(self, *, phy):
        self._phy = phy

        # TODO: remove when complete
        logging.warning("USB3 device support is not at all complete!")
        logging.warning("Do not expect -anything- to work!")

        #
        # I/O port
        #

        # General status signals.
        self.link_trained = Signal()

        # Temporary, debug signals.
        self.data_tap         = USBRawSuperSpeedStream()
        self.sending_ts1s     = Signal()
        self.sending_ts2s     = Signal()
        self.link_in_training = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Physical layer.
        #
        m.submodules.physical = physical = USB3PhysicalLayer(phy=self._phy)
        m.d.comb += [
            self.data_tap  .stream_eq(physical.source, omit={'ready'})
        ]

        #
        # Link layer.
        #
        m.submodules.link = link = USB3LinkLayer(physical_layer=physical)
        m.d.comb += [
            self.link_trained     .eq(link.trained),
            self.link_in_training .eq(link.in_training),
            self.sending_ts1s     .eq(link.sending_ts1s),
            self.sending_ts2s     .eq(link.sending_ts2s)
        ]


        #
        # Protocol layer.
        #
        # TODO

        #
        # Application layer.
        #
        # TODO


        return m
