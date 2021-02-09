#
# This file is part of LUNA.
#
# Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Hardware for communicating over various FPGAs' debug interfaces. """

from nmigen         import *
from nmigen.lib.cdc import FFSynchronizer
from nmigen.hdl.ast import ValueCastable
from nmigen.hdl.rec import DIR_FANIN, DIR_FANOUT

class ECP5DebugSPIBridge(Elaboratable, ValueCastable):
    """ Hardware that creates a virtual 'debug SPI' port, exposed over JTAG.

    WARNING: all signals are asynchronous to any internal clock domain -- they're
    synchronized to the JTAG scan chain clock. They should be synchronized before
    internal use.

    Attributes
    ----------
    sck: Signal(), output
        The serial clock used for JTAG transfers.
    sdi: Signal(), output
        The serial data received from TDI.
    sdo: Signal(), input
        The serial data to be transmitted. Used with the ER1 instruction.
    cs: Signal(), output
        Active high chip-select. Used with the ER1 instruction.

    sdo_alt: Signal(), input
        Alternate serial data to be transmitted. Used with the ER2 instruction.
    cs_alt: Signal(), output
        Alternate, active-high chip-select. Used with the ER2 instruction.
    """

    fields = ['sck', 'sdi', 'sdo', 'cs']
    layout = [
        ('sck', 1, DIR_FANIN),
        ('sdi', 1, DIR_FANIN),
        ('sdo', 1, DIR_FANOUT),
        ('cs',  1, DIR_FANIN),
    ]

    def __init__(self):

        #
        # I/O port
        #
        self.sck     = Signal()
        self.sdi     = Signal()
        self.sdo     = Signal()
        self.cs      = Signal()

        self.sdo_alt = Signal()
        self.cs_alt  = Signal()


    def elaborate(self, platform):
        m = Module()

        jtck   = Signal()
        jce1   = Signal()
        jce2   = Signal()
        jshift = Signal()


        # Instantiate our core JTAG interface, and hook it up to our signals.
        # This essentially grabs a connection to the ECP5's JTAG data chain when the ER1 or ER2
        # instructions are loaded into its instruction register.
        m.submodules.jtag = jtag = Instance("JTAGG",
            o_JTCK   = jtck,
            o_JTDI   = self.sdi,
            i_JTDO1  = self.sdo,
            i_JTDO2  = self.sdo_alt,
            o_JCE1   = jce1,
            o_JCE2   = jce2,
            o_JSHIFT = jshift
        )

        # As part of our switch to SPI, we'll want to create a clock that behaves according to a
        # sane SPI mode. Accordingly, we'll invert the JTAG clock to match the most common SPI CPOL.
        m.d.comb += self.sck.eq(~jtck)

        #
        # We'll need to keep our chip selects from going high prematurely, e.g. while the JTAG
        # clock is still running, but before we're presenting SPI data.
        #
        # Accordingly, we'll make our logic synchronous to the JTAG clock.
        # This is technically a hack, but it saves a bunch of logic.
        #

        # Create a clock domain clocked from our JTAG clock.
        m.domains.jtag = ClockDomain(local=True, clk_edge="neg")
        m.d.comb += ClockSignal("jtag").eq(jtck)

        # Create our chip selects. Note that these are based on two conditions:
        # - the JCE flags only go high when the right instruction is loaded; and
        # - the JSHIFT signal is only asserted when we're actually shifting data.
        m.d.jtag += [
            self.cs      .eq(jce1 & jshift),
            self.cs_alt  .eq(jce2 & jshift),
        ]

        return m


    #
    # Helpers that let us treat this object like a record, so it can be used
    # interchangeably with requested I/O objects.
    #

    @ValueCastable.lowermethod
    def as_value(self):
        return Record(self.layout)

    @ValueCastable.lowermethod
    def __getitem__(self, key):
        return {
            'sck': self.sck,
            'sdo': self.sdo,
            'sdi': self.sdi,
            'cs':  self.cs
        }[key]


    def _synchronize_(self, m, output, o_domain="sync", stages=2):
        """ Creates a synchronized copy of this interface's I/O. """

        # Synchronize our inputs...
        m.submodules += [
            FFSynchronizer(self.sck, output.sck, o_domain=o_domain, stages=stages),
            FFSynchronizer(self.sdi, output.sdi, o_domain=o_domain, stages=stages),
            FFSynchronizer(self.cs,  output.cs,  o_domain=o_domain, stages=stages),
        ]

        # ... and connect our output directly through.
        m.d.comb += self.sdo.eq(output.sdo)
