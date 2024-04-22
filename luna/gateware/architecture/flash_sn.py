#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth import Mux, Cat, C

from ..stream.generator  import StreamSerializer
from ..usb.usb2.transfer import USBInStreamInterface
from ..interface.flash   import ECP5ConfigurationFlashInterface, FlashUIDReader


class ECP5FlashUIDStringDescriptor(StreamSerializer):
    """ Custom runtime string descriptor that returns the Flash UID as a hex string. """

    def __init__(self):
        super().__init__(34, domain="usb", stream_type=USBInStreamInterface, max_length_width=16)

    def elaborate(self, platform):
        m = super().elaborate(platform)

        # Create the required modules to retrieve the flash UID.
        m.submodules.spi_bus  = spi_bus  = ECP5ConfigurationFlashInterface(bus=platform.request('spi_flash'), use_cs=True)
        m.submodules.flashuid = flashuid = FlashUIDReader(bus=spi_bus)

        # Helper function to convert a value to a hex string
        def get_hex_char(value, index):
            nibble = value.word_select(index ^ 1, 4)
            return Mux(nibble > 9, nibble - 10 + ord('a'), Cat(nibble, C(0b11, 2)))

        # Create string descriptor
        m.d.comb += [
            self.data[0].eq(self.data_length),
            self.data[1].eq(3),  # string type
        ]
        for i in range(16):
            m.d.comb += self.data[2+2*i].eq(get_hex_char(flashuid.uid, i))

        return m
