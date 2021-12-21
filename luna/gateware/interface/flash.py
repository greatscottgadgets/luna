#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Interfaces for working with an ECP5 MSPI configuration flash. """

from amaranth import Signal, Module, Cat, Elaboratable, Instance


class ECP5ConfigurationFlashInterface(Elaboratable):
    """ Gateware that creates a connection to an MSPI configuration flash.

    Automatically uses appropriate platform resources; this abstracts away details
    necessary to e.g. drive the MCLK lines on an ECP5, which has special handling.

    I/O port:
        B: spi -- The platform 

        I: sck -- The serial clock to be delivered to the SPI flash.
        I: sdi -- The SDI line to be passed through to the target flash.
        O: sdo -- The SDO line read from the target flash.
        I: cs  -- Active-high chip select line.
    """

    def __init__(self, *, bus, use_cs=False):
        """ Params:
            bus    -- The SPI bus object to connect to.
            use_cs -- Whether or not the CS line should be passed through to the target device.
        """

        self.bus = bus
        self.use_cs = use_cs

        #
        # I/O port
        #
        self.sck = Signal()
        self.sdi = Signal()
        self.sdo = Signal()
        self.cs  = Signal()


    def elaborate(self, platform):
        m = Module()

        # Get the ECP5 block that's responsible for driving the MCLK pin,
        # and drive it using our SCK line.
        user_mclk = Instance('USRMCLK', i_USRMCLKI=self.sck, i_USRMCLKTS=0)
        m.submodules += user_mclk

        # Connect up each of our other signals.
        m.d.comb += [
            self.bus.sdi   .eq(self.sdi),
            self.sdo       .eq(self.bus.sdo)
        ]

        if self.use_cs:
            m.d.comb += [
                self.bus.cs.o.eq(self.cs),
                self.bus.cs.oe.eq(1)
            ]
        else:
            m.d.comb += self.bus.cs.oe.eq(0)

        return m
