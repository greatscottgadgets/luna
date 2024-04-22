#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Interfaces for working with an ECP5 MSPI configuration flash. """

from amaranth import Signal, Module, Cat, Elaboratable, Instance, DomainRenamer, C


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
            self.bus.sdi.o .eq(self.sdi),
            self.sdo       .eq(self.bus.sdo.i)
        ]
        
        if self.use_cs:
            m.d.comb += self.bus.cs.o.eq(self.cs)
        if hasattr(self.bus.cs, "oe"):
            m.d.comb += self.bus.cs.oe.eq(self.use_cs)
        
        return m


class FlashUIDReader(Elaboratable):
    """ Gateware that implements a simple SPI Flash unique ID reader, triggered on reset. 
    
    I/O ports:

        B: bus  -- The SPI bus used to communicate with the device.
        
        O: uid  -- Contains the retrieved ID after the read is finished.
        O: done -- A signal that gets asserted when the read operation finishes.
    """

    # Opcode to read the chip's unique ID.
    READ_UID = 0x4B
    
    def __init__(self, bus, clock_period=4, domain="sync"):
        assert clock_period & (clock_period - 1) == 0  # only powers of 2
        self._domain = domain
        self.period  = clock_period
        self.bus     = bus

        #
        # I/O port
        #
        self.uid     = Signal(64)
        self.done    = Signal()

    def elaborate(self, platform):
        m = Module()

        # Clock generation and clock edge strobes
        cycles   = Signal(range(self.period))
        sck_fall = Signal()
        sck_rise = Signal()
        sck_d    = Signal()
        m.d.sync += sck_d.eq(self.bus.sck)
        m.d.comb += [
            sck_fall.eq( sck_d & ~self.bus.sck),  # falling edge
            sck_rise.eq(~sck_d &  self.bus.sck),  # rising edge
        ]
        
        # Output shift register and bit counter
        shreg_o = Signal(8, reset=self.READ_UID)
        count_o = Signal(range(128), reset=8*(1+4+8)-1)  # bytes: 1 opcode, 4 padding, 8 id

        with m.FSM(domain=self._domain):

            with m.State("XFER"):
                m.d.comb += [
                    self.bus.sck .eq(cycles[-1]),
                    self.bus.sdi .eq(shreg_o[-1]),
                    self.bus.cs  .eq(1),
                ]
                m.d.sync += cycles.eq(cycles + 1)

                # Read logic: latch on rising edge
                with m.If(sck_rise):
                    m.d.sync += self.uid.eq(Cat(self.bus.sdo, self.uid[:-1]))

                # Write logic: setup on falling edge
                with m.If(sck_fall):
                    m.d.sync += [
                        shreg_o .eq(Cat(C(0,1), shreg_o[:-1])),
                        count_o .eq(count_o - 1),
                    ]
                    with m.If(count_o == 0):
                        m.next = 'END'
            
            with m.State("END"):
                m.d.comb += self.done.eq(1)

        # Convert our sync domain to the domain requested by the user, if necessary.
        if self._domain != "sync":
            m = DomainRenamer({"sync": self._domain})(m)

        return m