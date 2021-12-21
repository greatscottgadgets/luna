#
# This file is part of LUNA.
#
# Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Hardware for communicating over various FPGAs' debug interfaces. """

from amaranth         import *
from amaranth.lib.cdc import FFSynchronizer, PulseSynchronizer
from amaranth.hdl.ast import ValueCastable
from amaranth.hdl.rec import DIR_FANIN, DIR_FANOUT

from ..utils        import falling_edge_detected, rising_edge_detected
from .spi           import SPIRegisterInterface

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



class JTAGCommandInterface(Elaboratable):
    """ Interface that allow us to receive simple register-style commands over ECP5 JTAGG.

    This module works in an emulation of JTAG, except both instruction and data are shifted
    in the SHIFT-DR state. To shift an instruction, place the Lattice ER1 instruction into the
    JTAG IR, and then shift the instruction in as data. To shift data, place the Lattice ER2
    instruction into the JTAG IR, and then shift data normally.


    Attributes
    ----------
    command: Signal(command_size), output
        The command read from the SPI bus.
    command_ready: Signal(), output
        Strobes high to indicate a new command is ready.

    word_received: Signal(word_size), output
        The most recent word received.
    word_complete: Signal(), output
        Strobe indicating a new word is present on word_in.
    word_to_send: Signal(word_size), input
        The word to be transmitted; latched in on next word_complete and while cs is low
    """

    def __init__(self, command_size=8, word_size=32, output_domain="sync"):
        self.command_size   = command_size
        self.word_size      = word_size
        self._output_domain = output_domain

        #
        # I/O port.
        #

        # Command I/O.
        self.command        = Signal(self.command_size)
        self.command_ready  = Signal()

        # Data I/O
        self.word_received  = Signal(self.word_size)
        self.word_to_send   = Signal.like(self.word_received)
        self.word_complete  = Signal()

        # Status
        self.idle    = Signal()
        self.stalled = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Instruction and data registers.
        #
        ir_size              = self.command_size + 1
        dr_size              = self.word_size + 1
        instruction_register = Signal(ir_size, reset=(2 ** ir_size - 1))
        data_register        = Signal(dr_size, reset=(2 ** dr_size - 1))

        #
        # JTAG interface.
        #

        jtag_clk = Signal()
        jtag_tdi = Signal()

        jtag_tdo_instruction = Signal()
        jtag_tdo_data        = Signal()
        jtag_ce_instruction  = Signal()
        jtag_ce_data         = Signal()
        jtag_in_shift_dr     = Signal()
        jtag_not_in_reset    = Signal()
        jtag_in_reset        = Signal()
        jtag_in_update_dr    = Signal()
        jtag_rti_instruction = Signal()

        # Instantiate our core JTAG interface, and hook it up to our signals.
        # This essentially grabs a connection to the ECP5's JTAG data chain when the ER1 or ER2
        # instructions are loaded into its instruction register.
        m.submodules.jtag =  Instance("JTAGG",
            o_JTCK    = jtag_clk,
            o_JTDI    = jtag_tdi,
            i_JTDO1   = jtag_tdo_instruction,
            i_JTDO2   = jtag_tdo_data,
            o_JCE1    = jtag_ce_instruction,
            o_JCE2    = jtag_ce_data,
            o_JSHIFT  = jtag_in_shift_dr,
            o_JRSTN   = jtag_not_in_reset,
            o_JUPDATE = jtag_in_update_dr,
            o_JRTI1   = jtag_rti_instruction,
        )
        m.d.comb += jtag_in_reset.eq(~jtag_not_in_reset)

        # Edges on the JTAGG signals line up directly with the JTCK rising edge,
        # so create a delayed version of the clock to sample them reliably.
        jtag_clk_delayed = Signal()
        m.d.sync += jtag_clk_delayed.eq(jtag_clk)

        # Detect a rising edge in jtag_clk.
        jtag_strobe = rising_edge_detected(m, jtag_clk_delayed)

        # Always output the end of our scan chains.
        m.d.comb += [
            jtag_tdo_instruction  .eq(instruction_register[0]),
            jtag_tdo_data         .eq(data_register[0]),
        ]

        with m.If(jtag_strobe):
            # Once we're actively shifting an instruction over JTAG, capture it.
            shifting_instruction = Signal()
            m.d.sync += shifting_instruction.eq(jtag_ce_instruction & jtag_in_shift_dr)
            with m.If(jtag_in_reset):
                m.d.sync += instruction_register.eq(instruction_register.reset)
            with m.Elif(shifting_instruction):
                m.d.sync += instruction_register.eq(Cat(instruction_register[1:], jtag_tdi))


            # Once we're actively shifting data over JTAG, capture it.
            shifting_data = Signal()
            m.d.sync += shifting_data.eq(jtag_ce_data & jtag_in_shift_dr)
            with m.If(jtag_in_reset):
                m.d.sync += data_register.eq(data_register.reset)
            with m.Elif(shifting_data):
                m.d.sync += data_register.eq(Cat(data_register[1:], jtag_tdi))
            with m.Elif(jtag_rti_instruction):
                m.d.sync += data_register.eq(self.word_to_send)


        # Create our event strobes.
        command_ready = Signal()
        data_ready    = Signal()

        # Connect up our "data/command ready" signals.
        m.d.comb += [
           command_ready  .eq(falling_edge_detected(m, shifting_instruction)),
           data_ready     .eq(falling_edge_detected(m, shifting_data)),
        ]

        # Latch our output data when new data is ready.
        with m.If(command_ready):
            m.d.sync += self.command.eq(instruction_register[1:])
        with m.If(data_ready):
            m.d.sync += self.word_received.eq(data_register[1:])

        # Create sync-domain versions of our data/command ready signals, which are delayed
        # one cycle from our internal ones, to coincide with the point at which our data is latched.
        m.d.sync += [
            self.command_ready  .eq(command_ready),
            self.word_complete  .eq(data_ready)
        ]

        return m



class JTAGRegisterInterface(SPIRegisterInterface):
    """ JTAG-carried version of our SPI register interface. """


    def __init__(self, address_size=15, register_size=32, default_read_value=0, support_size_autonegotiation=True):
        """
        Parameters:
            address_size       -- the size of an address, in bits; recommended to be one bit
                                  less than a binary number, as the write command is formed by adding a one-bit
                                  write flag to the start of every address
            register_size      -- The size of any given register, in bits.
            default_read_value -- The read value read from a non-existent or write-only register.

            support_size_autonegotiation --
                If set, register 0 is used as a size auto-negotiation register. Functionally equivalent to
                calling .support_size_autonegotiation(); see its documentation for details on autonegotiation.
        """

        self.address_size  = address_size
        self.register_size = register_size
        self.default_read_value  = default_read_value

        #
        # I/O port
        #
        self.idle    = Signal()
        self.stalled = Signal()

        #
        # Internal details.
        #

        # Instantiate an SPI command transciever submodule.
        self.interface = JTAGCommandInterface(command_size=address_size + 1, word_size=register_size)

        # Create a new, empty dictionary mapping registers to their signals.
        self.registers = {}

        # Create signals for each of our register control signals.
        self._is_write = Signal()
        self._address  = Signal(self.address_size)

        if support_size_autonegotiation:
            self.support_size_autonegotiation()


    def _connect_interface(self, m):
        pass
