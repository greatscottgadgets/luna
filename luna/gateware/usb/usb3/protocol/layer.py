#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from nmigen import *

from ...stream  import USBRawSuperSpeedStream



class USB3ProtocolLayer(Elaboratable):
    """ Abstraction encapsulating the USB3 protocol layer hardware. """

    def __init__(self, *, link_layer):
        self._link = link_layer


    def elaborate(self, platform):
        m = Module()
        link = self._link

        #
        # Placeholder.
        #

        # For now, as a placeholder, black-hole all received header packets.
        m.d.comb += link.consume_header.eq(1)

        return m
