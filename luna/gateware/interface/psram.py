#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Interfaces to LUNA's PSRAM chips."""

from amaranth import Const, Signal, Module, Cat, Elaboratable, Record, ClockSignal, ResetSignal, Instance
from amaranth.hdl.rec import DIR_FANIN, DIR_FANOUT
from amaranth.lib.cdc import FFSynchronizer


class HyperBusPHY(Record):
    """ Record representing a 16-bit HyperBus interface for use with a 2:1 PHY module. """

    def __init__(self):
        super().__init__([
            ('clk_en', 1, DIR_FANOUT),
            ('dq', [
                ('i', 16, DIR_FANIN),
                ('o', 16, DIR_FANOUT),
                ('e', 1,  DIR_FANOUT),
            ]),
            ('rwds', [
                ('i', 2,  DIR_FANIN),
                ('o', 2,  DIR_FANOUT),
                ('e', 1,  DIR_FANOUT),
            ]),
            ('cs',     1, DIR_FANOUT),
            ('reset',  1, DIR_FANOUT)
        ])


class HyperRAMInterface(Elaboratable):
    """ Gateware interface to HyperRAM series self-refreshing DRAM chips.

    I/O port:
        B: phy              -- The primary physical connection to the DRAM chip.

        I: address[32]      -- The address to be targeted by the given operation.
        I: register_space   -- When set to 1, read and write requests target registers instead of normal RAM.
        I: perform_write    -- When set to 1, a transfer request is viewed as a write, rather than a read.
        I: single_page      -- If set, data accesses will wrap around to the start of the current page when done.
        I: start_transfer   -- Strobe that goes high for 1-8 cycles to request a read operation.
                               [This added duration allows other clock domains to easily perform requests.]
        I: final_word       -- Flag that indicates the current word is the last word of the transaction.

        O: read_data[16]    -- word that holds the 16 bits most recently read from the PSRAM
        I: write_data[16]   -- word that accepts the data to output during this transaction

        O: idle             -- High whenever the transmitter is idle (and thus we can start a new piece of data.)
        O: read_ready       -- Strobe that indicates when new data is ready for reading
        O: write_ready      -- Strobe that indicates `write_data` has been latched and is ready for new data
    """

    LOW_LATENCY_CLOCKS  = 7
    HIGH_LATENCY_CLOCKS = 14

    def __init__(self, *, phy):
        """
        Parmeters:
            phy           -- The RAM record that should be connected to this RAM chip.
        """

        #
        # I/O port.
        #
        self.phy              = phy

        # Control signals.
        self.address          = Signal(32)
        self.register_space   = Signal()
        self.perform_write    = Signal()
        self.single_page      = Signal()
        self.start_transfer   = Signal()
        self.final_word       = Signal()

        # Status signals.
        self.idle             = Signal()
        self.read_ready       = Signal()
        self.write_ready      = Signal()

        # Data signals.
        self.read_data        = Signal(16)
        self.write_data       = Signal(16)


    def elaborate(self, platform):
        m = Module()

        #
        # Latched control/addressing signals.
        #
        is_read         = Signal()
        is_register     = Signal()
        current_address = Signal(32)
        is_multipage    = Signal()

        #
        # FSM datapath signals.
        #

        # Tracks whether we need to add an extra latency period between our
        # command and the data body.
        extra_latency   = Signal()

        # Tracks how many cycles of latency we have remaining between a command
        # and the relevant data stages.
        latency_clocks_remaining  = Signal(range(0, self.HIGH_LATENCY_CLOCKS + 1))

        # Store last edge values of RWDS and DQ lines.
        # This is used to handle clock inversion cases.
        last_half_rwds = Signal()
        last_half_dq   = Signal(len(self.phy.dq.i)//2)

        #
        # Core operation FSM.
        #

        # Provide defaults for our control/status signals.
        m.d.sync += [
            self.phy.clk_en     .eq(1),
            self.phy.cs         .eq(1),
            self.phy.rwds.e     .eq(0),
            self.phy.dq.e       .eq(0),
        ]
        m.d.comb += self.write_ready.eq(0),

        # Commands, in order of bytes sent:
        #   - WRBAAAAA
        #     W         => selects read or write; 1 = read, 0 = write
        #      R        => selects register or memory; 1 = register, 0 = memory
        #       B       => selects burst behavior; 0 = wrapped, 1 = linear
        #        AAAAA  => address bits [27:32]
        #
        #   - AAAAAAAA  => address bits [19:27]
        #   - AAAAAAAA  => address bits [11:19]
        #   - AAAAAAAA  => address bits [ 3:16]
        #   - 00000000  => [reserved]
        #   - 00000AAA  => address bits [ 0: 3]
        ca = Signal(48)
        m.d.comb += ca.eq(Cat(
            current_address[0:3],
            Const(0, 13),
            current_address[3:32],
            is_multipage,
            is_register,
            is_read
        ))

        with m.FSM() as fsm:

            # IDLE state: waits for a transaction request
            with m.State('IDLE'):
                m.d.comb += self.idle        .eq(1)
                m.d.sync += self.phy.clk_en  .eq(0)

                # Once we have a transaction request, latch in our control
                # signals, and assert our chip-select.
                with m.If(self.start_transfer):
                    m.next = 'LATCH_RWDS'

                    m.d.sync += [
                        is_read             .eq(~self.perform_write),
                        is_register         .eq(self.register_space),
                        is_multipage        .eq(~self.single_page),
                        current_address     .eq(self.address),
                        self.phy.dq.o       .eq(0),
                    ]

                with m.Else():
                    m.d.sync += self.phy.cs.eq(0)


            # LATCH_RWDS -- latch in the value of the RWDS signal,
            # which determines our read/write latency.
            with m.State("LATCH_RWDS"):
                m.d.sync += extra_latency.eq(self.phy.rwds.i),
                m.d.sync += self.phy.clk_en.eq(0)
                m.next="SHIFT_COMMAND0"


            # SHIFT_COMMANDx -- shift each of our command words out
            with m.State('SHIFT_COMMAND0'):
                # Output our first byte of our command.
                m.d.sync += [
                    self.phy.dq.o.eq(ca[32:48]),
                    self.phy.dq.e.eq(1)
                ]
                m.next = 'SHIFT_COMMAND1'

            with m.State('SHIFT_COMMAND1'):
                m.d.sync += [
                    self.phy.dq.o.eq(ca[16:32]),
                    self.phy.dq.e.eq(1)
                ]
                m.next = 'SHIFT_COMMAND2'

            with m.State('SHIFT_COMMAND2'):
                m.d.sync += [
                    self.phy.dq.o.eq(ca[0:16]),
                    self.phy.dq.e.eq(1)
                ]

                # If we have a register write, we don't need to handle
                # any latency. Move directly to our SHIFT_DATA state.
                with m.If(is_register & ~is_read):
                    m.next = 'WRITE_DATA'

                # Otherwise, react with either a short period of latency
                # or a longer one, depending on what the RAM requested via
                # RWDS.
                with m.Else():
                    m.next = "HANDLE_LATENCY"

                    # FIXME: our HyperRAM part has a fixed latency, but we could need to detect 
                    # different variants from the configuration register in the future.
                    with m.If(extra_latency | 1):
                        m.d.sync += latency_clocks_remaining.eq(self.HIGH_LATENCY_CLOCKS-2)
                    with m.Else():
                        m.d.sync += latency_clocks_remaining.eq(self.LOW_LATENCY_CLOCKS-2)


            # HANDLE_LATENCY -- applies clock cycles until our latency period is over.
            with m.State('HANDLE_LATENCY'):
                m.d.sync += latency_clocks_remaining.eq(latency_clocks_remaining - 1)

                with m.If(latency_clocks_remaining == 0):
                    with m.If(is_read):
                        m.next = 'READ_DATA'
                    with m.Else():
                        m.next = 'WRITE_DATA'


            # READ_DATA -- reads words from the PSRAM
            with m.State('READ_DATA'):

                # Store data sampled in last edge.
                m.d.sync += [
                    last_half_rwds .eq(self.phy.rwds.i[0]),
                    last_half_dq   .eq(self.phy.dq.i[:8])
                ]

                # If RWDS has changed, the host has just sent us new data.
                # Sample it, and indicate that we now have a valid piece of new data.
                with m.If(self.phy.rwds.i == 0b10):
                    m.d.comb += [
                        self.read_data     .eq(self.phy.dq.i),
                        self.read_ready    .eq(1),
                    ]

                    # If our controller is done with the transaction, end it.
                    with m.If(self.final_word):
                        m.next = 'RECOVERY'

                # Manage clock inversion: the data is divided between the current cycle 
                # and the preceding one.
                with m.Elif(Cat(self.phy.rwds.i[1], last_half_rwds) == 0b10):
                    m.d.comb += [
                        self.read_data     .eq(Cat(self.phy.dq.i[8:], last_half_dq)),
                        self.read_ready    .eq(1),
                    ]

                    # If our controller is done with the transaction, end it.
                    with m.If(self.final_word):
                        m.next = 'RECOVERY'

            # WRITE_DATA -- write a word to the PSRAM
            with m.State("WRITE_DATA"):
                m.d.sync += [
                    self.phy.dq.o    .eq(self.write_data),
                    self.phy.dq.e    .eq(1),
                    self.phy.rwds.e  .eq(~is_register),
                    self.phy.rwds.o  .eq(0),
                ]
                m.d.comb += self.write_ready.eq(1),

                # If we just finished a register write, we're done -- there's no need for recovery.
                with m.If(is_register):
                    m.next = 'IDLE'

                with m.Elif(self.final_word):
                    m.next = 'RECOVERY'


            # RECOVERY state: wait for the required period of time before a new transaction
            with m.State('RECOVERY'):
                m.d.sync += [
                    self.phy.cs     .eq(0),
                    self.phy.clk_en .eq(0),
                    last_half_rwds  .eq(0),
                    last_half_dq    .eq(0),

                ]

                # TODO: implement recovery
                m.next = 'IDLE'



        return m


class HyperRAMPHY(Elaboratable):
    """ Gateware PHY for HyperRAM series self-refreshing DRAM chips.

    I/O port:
        B: bus              -- The primary physical connection to the DRAM chip.
    """

    def __init__(self, *, bus, in_skew=None, out_skew=None, clock_skew=None):
        self.bus = bus
        self.phy = HyperBusPHY()

    def elaborate(self, platform):
        m = Module()

        m.submodules += [
            FFSynchronizer(self.phy.cs,     self.bus.cs.o,    stages=3),
            FFSynchronizer(self.phy.rwds.e, self.bus.rwds.oe, stages=3),
            FFSynchronizer(self.phy.dq.e,   self.bus.dq.oe,   stages=3),
        ]

        # Clock
        clk_out = Signal()
        m.submodules += [
            Instance("ODDRX1F",
                i_D0=self.phy.clk_en,
                i_D1=0,
                i_SCLK=ClockSignal(),
                i_RST=ResetSignal(),
                o_Q=clk_out,
            ),
            Instance("DELAYF",
                i_A=clk_out,
                o_Z=self.bus.clk.o,
                # TODO: connect up move/load/dir
                p_DEL_VALUE=int(2e-9 / 25e-12),
            ),
        ]

        # RWDS out
        m.submodules += [
            Instance("ODDRX1F",
                i_D0=self.phy.rwds.o[1],
                i_D1=self.phy.rwds.o[0],
                i_SCLK=ClockSignal(),
                i_RST=ResetSignal(),
                o_Q=self.bus.rwds.o,
            ),
        ]

        # RWDS in
        rwds_in = Signal()
        m.submodules += [
            Instance("DELAYF",
                i_A=self.bus.rwds.i,
                o_Z=rwds_in,
                # TODO: connect up move/load/dir
                p_DEL_VALUE=int(0e-9 / 25e-12),
            ),
            Instance("IDDRX1F",
                i_D=rwds_in,
                i_SCLK=ClockSignal(),
                i_RST=ResetSignal(),
                o_Q0=self.phy.rwds.i[1],
                o_Q1=self.phy.rwds.i[0],
            ),
        ]

        # DQ
        for i in range(8):
            # Out
            m.submodules += [
                Instance("ODDRX1F",
                    i_D0=self.phy.dq.o[i+8],
                    i_D1=self.phy.dq.o[i],
                    i_SCLK=ClockSignal(),
                    i_RST=ResetSignal(),
                    o_Q=self.bus.dq.o[i],
                ),
            ]

            # In
            dq_in = Signal(name=f"dq_in{i}")
            m.submodules += [
                Instance("DELAYF",
                    i_A=self.bus.dq.i[i],
                    o_Z=dq_in,
                    # TODO: connect up move/load/dir
                    p_DEL_VALUE=int(0e-9 / 25e-12),
                ),
                Instance("IDDRX1F",
                    i_D=dq_in,
                    i_SCLK=ClockSignal(),
                    i_RST=ResetSignal(),
                    o_Q0=self.phy.dq.i[i+8],
                    o_Q1=self.phy.dq.i[i],
                ),
            ]

        return m


class HyperBusDQSPHY(Record):
    """ Record representing a 32-bit HyperBus interface on a DQS group for use with a 4:1 PHY module. """

    def __init__(self):
        super().__init__([
            ('clk_en', 2, DIR_FANOUT),
            ('dq', [
                ('i', 32, DIR_FANIN),
                ('o', 32, DIR_FANOUT),
                ('e', 1,  DIR_FANOUT),
            ]),
            ('rwds', [
                ('i', 4,  DIR_FANIN),
                ('o', 4,  DIR_FANOUT),
                ('e', 1,  DIR_FANOUT),
            ]),
            ('cs',        1, DIR_FANOUT),
            ('reset',     1, DIR_FANOUT),
            ('read',      2, DIR_FANIN),
            ('datavalid', 1, DIR_FANOUT),
            ('burstdet',  1, DIR_FANOUT)
        ])



class HyperRAMDQSInterface(Elaboratable):
    """ Gateware interface to HyperRAM series self-refreshing DRAM chips, using ECP5 DQS logic.

    I/O port:
        B: phy              -- The primary physical connection to the DRAM chip.

        I: address[32]      -- The address to be targeted by the given operation.
        I: register_space   -- When set to 1, read and write requests target registers instead of normal RAM.
        I: perform_write    -- When set to 1, a transfer request is viewed as a write, rather than a read.
        I: single_page      -- If set, data accesses will wrap around to the start of the current page when done.
        I: start_transfer   -- Strobe that goes high for 1-8 cycles to request a read operation.
                               [This added duration allows other clock domains to easily perform requests.]
        I: final_word       -- Flag that indicates the current word is the last word of the transaction.

        O: read_data[32]    -- word that holds the 32 bits most recently read from the PSRAM
        I: write_data[32]   -- word that accepts the data to output during this transaction

        O: idle             -- High whenever the transmitter is idle (and thus we can start a new piece of data.)
        O: read_ready       -- Strobe that indicates when new data is ready for reading
        O: write_ready      -- Strobe that indicates `write_data` has been latched and is ready for new data
    """

    LOW_LATENCY_CLOCKS  = 3
    HIGH_LATENCY_CLOCKS = 5

    def __init__(self, *, phy):
        """
        Parmeters:
            phy           -- The RAM record that should be connected to this RAM chip.
        """

        #
        # I/O port.
        #
        self.phy              = phy

        # Control signals.
        self.address          = Signal(32)
        self.register_space   = Signal()
        self.perform_write    = Signal()
        self.single_page      = Signal()
        self.start_transfer   = Signal()
        self.final_word       = Signal()

        # Status signals.
        self.idle             = Signal()
        self.read_ready       = Signal()
        self.write_ready      = Signal()

        # Data signals.
        self.read_data        = Signal(32)
        self.write_data       = Signal(32)


    def elaborate(self, platform):
        m = Module()

        #
        # Latched control/addressing signals.
        #
        is_read         = Signal()
        is_register     = Signal()
        current_address = Signal(32)
        is_multipage    = Signal()

        #
        # FSM datapath signals.
        #

        # Tracks whether we need to add an extra latency period between our
        # command and the data body.
        extra_latency   = Signal()

        # Tracks how many cycles of latency we have remaining between a command
        # and the relevant data stages.
        latency_clocks_remaining  = Signal(range(0, self.HIGH_LATENCY_CLOCKS + 1))

        #
        # Core operation FSM.
        #

        # Provide defaults for our control/status signals.
        m.d.sync += [
            self.phy.clk_en     .eq(0b11),
            self.phy.cs         .eq(1),
            self.phy.rwds.e     .eq(0),
            self.phy.dq.e       .eq(0),
            self.phy.read       .eq(0),
        ]
        m.d.comb += self.write_ready.eq(0),

        # Commands, in order of bytes sent:
        #   - WRBAAAAA
        #     W         => selects read or write; 1 = read, 0 = write
        #      R        => selects register or memory; 1 = register, 0 = memory
        #       B       => selects burst behavior; 0 = wrapped, 1 = linear
        #        AAAAA  => address bits [27:32]
        #
        #   - AAAAAAAA  => address bits [19:27]
        #   - AAAAAAAA  => address bits [11:19]
        #   - AAAAAAAA  => address bits [ 3:16]
        #   - 00000000  => [reserved]
        #   - 00000AAA  => address bits [ 0: 3]
        ca = Signal(48)
        m.d.comb += ca.eq(Cat(
            current_address[0:3],
            Const(0, 13),
            current_address[3:32],
            is_multipage,
            is_register,
            is_read
        ))

        with m.FSM() as fsm:

            # IDLE state: waits for a transaction request
            with m.State('IDLE'):
                m.d.comb += self.idle        .eq(1)
                m.d.sync += self.phy.clk_en  .eq(0)

                # Once we have a transaction request, latch in our control
                # signals, and assert our chip-select.
                with m.If(self.start_transfer):
                    m.next = 'LATCH_RWDS'

                    m.d.sync += [
                        is_read             .eq(~self.perform_write),
                        is_register         .eq(self.register_space),
                        is_multipage        .eq(~self.single_page),
                        current_address     .eq(self.address),
                        self.phy.dq.o       .eq(0),
                    ]

                with m.Else():
                    m.d.sync += self.phy.cs.eq(0)


            # LATCH_RWDS -- latch in the value of the RWDS signal,
            # which determines our read/write latency.
            with m.State("LATCH_RWDS"):
                m.d.sync += extra_latency.eq(self.phy.rwds.i),
                m.d.sync += self.phy.clk_en.eq(0b11)
                m.next="SHIFT_COMMAND0"


            # SHIFT_COMMANDx -- shift each of our command words out
            with m.State('SHIFT_COMMAND0'):
                # Output the first 32 bits of our command.
                m.d.sync += [
                    self.phy.dq.o.eq(Cat(ca[16:48])),
                    self.phy.dq.e.eq(1),
                ]
                m.next = 'SHIFT_COMMAND1'

            with m.State('SHIFT_COMMAND1'):
                # Output the remaining 32 bits of our command.
                m.d.sync += [
                    self.phy.dq.o.eq(Cat(Const(0, 16), ca[0:16])),
                    self.phy.dq.e.eq(1),
                ]

                # If we have a register write, we don't need to handle
                # any latency. Move directly to our SHIFT_DATA state.
                with m.If(is_register & ~is_read):
                    m.next = 'WRITE_DATA'

                # Otherwise, react with either a short period of latency
                # or a longer one, depending on what the RAM requested via
                # RWDS.
                with m.Else():
                    m.next = "HANDLE_LATENCY"

                    # FIXME: our HyperRAM part has a fixed latency, but we could need to detect 
                    # different variants from the configuration register in the future.
                    with m.If(extra_latency | 1):
                        m.d.sync += latency_clocks_remaining.eq(self.HIGH_LATENCY_CLOCKS)
                    with m.Else():
                        m.d.sync += latency_clocks_remaining.eq(self.LOW_LATENCY_CLOCKS)


            # HANDLE_LATENCY -- applies clock cycles until our latency period is over.
            with m.State('HANDLE_LATENCY'):
                m.d.sync += latency_clocks_remaining.eq(latency_clocks_remaining - 1)

                with m.If(latency_clocks_remaining == 0):
                    with m.If(is_read):
                        m.next = 'READ_DATA'
                    with m.Else():
                        m.next = 'WRITE_DATA'


            # READ_DATA -- reads words from the PSRAM
            with m.State('READ_DATA'):
                m.d.sync += self.phy.read.eq(0b11)

                datavalid_delay = Signal()
                m.d.sync += datavalid_delay.eq(self.phy.datavalid)

                with m.If(self.phy.datavalid):
                    m.d.comb += [
                        self.read_data     .eq(self.phy.dq.i),
                        self.read_ready    .eq(1),
                    ]

                    # If our controller is done with the transaction, end it.
                    with m.If(self.final_word):
                        m.d.sync += self.phy.clk_en.eq(0),
                        m.next = 'RECOVERY'

            # WRITE_DATA -- write a word to the PSRAM
            with m.State("WRITE_DATA"):
                m.d.sync += [
                    self.phy.dq.o    .eq(self.write_data),
                    self.phy.dq.e    .eq(1),
                    self.phy.rwds.e  .eq(~is_register),
                    self.phy.rwds.o  .eq(0),
                ]
                m.d.comb += self.write_ready.eq(1),

                # If we just finished a register write, we're done -- there's no need for recovery.
                with m.If(is_register):
                    m.next = 'IDLE'

                with m.Elif(self.final_word):
                    m.next = 'RECOVERY'


            # RECOVERY state: wait for the required period of time before a new transaction
            with m.State('RECOVERY'):
                m.d.sync += self.phy.clk_en .eq(0)

                # TODO: implement recovery
                m.next = 'IDLE'



        return m


class HyperRAMDQSPHY(Elaboratable):
    """ Gateware PHY for HyperRAM series self-refreshing DRAM chips, using ECP5 DQS logic.

    I/O port:
        B: bus              -- The primary physical connection to the DRAM chip.
    """

    def __init__(self, *, bus, in_skew=None, out_skew=None, clock_skew=None):
        self.bus = bus
        self.phy = HyperBusDQSPHY()

    def elaborate(self, platform):
        m = Module()

        # Handle initial DDRDLL lock & delay code update
        pause = Signal()
        freeze = Signal()
        lock = Signal()
        uddcntln = Signal()
        counter = Signal(range(9))
        m.d.sync += counter.eq(counter + 1)
        with m.FSM() as fsm:
            with m.State('INIT'):
                m.d.sync += [
                    pause.eq(1),
                    freeze.eq(0),
                    uddcntln.eq(0),
                ]

                with m.If(lock):
                    m.next = 'FREEZE'
                    m.d.sync += [
                        freeze.eq(1),
                        counter.eq(0),
                    ]

            with m.State('FREEZE'):
                with m.If(counter == 8):
                    m.next = 'UPDATE'
                    m.d.sync += [
                        uddcntln.eq(1),
                        counter.eq(0),
                    ]

            with m.State('UPDATE'):
                with m.If(counter == 8):
                    m.next = 'UPDATED'
                    m.d.sync += [
                        uddcntln.eq(0),
                        counter.eq(0),
                    ]

            with m.State('UPDATED'):
                with m.If(counter == 8):
                    m.next = 'UNPAUSE'
                    m.d.sync += [
                        pause.eq(0),
                        counter.eq(0),
                    ]

            with m.State('UNPAUSE'):
                pass


        # DQS (RWDS) input
        rwds_o = Signal()
        rwds_oe_n = Signal()
        rwds_in = Signal()

        dqsr90 = Signal()
        dqsw = Signal()
        dqsw270 = Signal()
        ddrdel = Signal()
        readptr = Signal(3)
        writeptr = Signal(3)
        m.submodules += [
            Instance("DDRDLLA",
                i_CLK=ClockSignal("fast"),
                i_RST=ResetSignal(),
                i_FREEZE=freeze,
                i_UDDCNTLN=uddcntln,
                o_DDRDEL=ddrdel,
                o_LOCK=lock,
            ),
            Instance("BB",
                i_I=rwds_o,
                i_T=rwds_oe_n,
                o_O=rwds_in,
                io_B=self.bus.rwds.io
            ),
            Instance("TSHX2DQSA",
                i_RST=ResetSignal(),
                i_ECLK=ClockSignal("fast"),
                i_SCLK=ClockSignal(),
                i_DQSW=dqsw,
                i_T0=~self.phy.rwds.e,
                i_T1=~self.phy.rwds.e,
                o_Q=rwds_oe_n
            ),
            Instance("DQSBUFM",
                i_SCLK=ClockSignal(),
                i_ECLK=ClockSignal("fast"),
                i_RST=ResetSignal(),

                i_DQSI=rwds_in,
                i_DDRDEL=ddrdel,
                i_PAUSE=pause,
                i_READ0=self.phy.read[0],
                i_READ1=self.phy.read[1],
                # TODO: may need to tune at runtime by trying different values & checking for BURSTDET high
                i_READCLKSEL0=0,
                i_READCLKSEL1=1,
                i_READCLKSEL2=0,

                i_RDLOADN=0,
                i_RDMOVE=0,
                i_RDDIRECTION=1,
                i_WRLOADN=0,
                i_WRMOVE=0,
                i_WRDIRECTION=1,

                o_DQSR90=dqsr90,
                o_DQSW=dqsw,
                o_DQSW270=dqsw270,
                **{f"o_RDPNTR{i}": readptr[i] for i in range(len(readptr))},
                **{f"o_WRPNTR{i}": writeptr[i] for i in range(len(writeptr))},

                o_DATAVALID=self.phy.datavalid,
                o_BURSTDET=self.phy.burstdet,
            ),
        ]

        # Clock
        clk_out = Signal()
        clk_dqsw270 = Signal()
        m.submodules += [
            Instance("DELAYG",
                p_DEL_MODE="DQS_CMD_CLK",
                i_A=clk_out,
                o_Z=self.bus.clk,
            ),
            Instance("ODDRX2F",
                i_D0=0,
                i_D1=self.phy.clk_en[1],
                i_D2=0,
                i_D3=self.phy.clk_en[0],
                i_SCLK=ClockSignal(),
                i_ECLK=ClockSignal("fast"),
                i_RST=ResetSignal(),
                o_Q=clk_out,
            ),
        ]

        # CS
        cs_out = Signal()
        m.submodules += [
            Instance("DELAYG",
                p_DEL_MODE="DQS_CMD_CLK",
                i_A=cs_out,
                o_Z=self.bus.cs,
            ),
            Instance("ODDRX2F",
                i_D0=~self.phy.cs,
                i_D1=~self.phy.cs,
                i_D2=~self.phy.cs,
                i_D3=~self.phy.cs,
                i_SCLK=ClockSignal(),
                i_ECLK=ClockSignal("fast"),
                i_RST=ResetSignal(),
                o_Q=cs_out,
            ),
        ]

        # RWDS out
        m.submodules += [
            Instance("ODDRX2DQSB",
                i_DQSW=dqsw,
                i_D0=self.phy.rwds.o[3],
                i_D1=self.phy.rwds.o[2],
                i_D2=self.phy.rwds.o[1],
                i_D3=self.phy.rwds.o[0],
                i_SCLK=ClockSignal(),
                i_ECLK=ClockSignal("fast"),
                i_RST=ResetSignal(),
                o_Q=rwds_o,
            ),
        ]

        # DQ
        for i in range(8):
            dq_in   = Signal(name=f"dq_in{i}")
            dq_in_delayed   = Signal(name=f"dq_in_delayed{i}")
            dq_oe_n = Signal(name=f"dq_oe_n{i}")
            dq_o    = Signal(name=f"dq_o{i}")
            # Out
            m.submodules += [
                # Tristate
                Instance("BB",
                    i_I=dq_o,
                    i_T=dq_oe_n,
                    o_O=dq_in,
                    io_B=self.bus.dq.io[i]
                ),
                Instance("TSHX2DQA",
                    i_T0=~self.phy.dq.e,
                    i_T1=~self.phy.dq.e,
                    i_SCLK=ClockSignal(),
                    i_ECLK=ClockSignal("fast"),
                    i_DQSW270=dqsw270,
                    i_RST=ResetSignal(),
                    o_Q=dq_oe_n,
                ),

                # Output
                Instance("ODDRX2DQA",
                    i_DQSW270=dqsw270,
                    i_D0=self.phy.dq.o[i+24],
                    i_D1=self.phy.dq.o[i+16],
                    i_D2=self.phy.dq.o[i+8],
                    i_D3=self.phy.dq.o[i],
                    i_SCLK=ClockSignal(),
                    i_ECLK=ClockSignal("fast"),
                    i_RST=ResetSignal(),
                    o_Q=dq_o,
                ),

                # Input
                Instance("DELAYG",
                    p_DEL_MODE="DQS_ALIGNED_X2",
                    i_A=dq_in,
                    o_Z=dq_in_delayed,
                ),
                Instance("IDDRX2DQA",
                    i_D=dq_in_delayed,
                    i_DQSR90=dqsr90,
                    i_SCLK=ClockSignal(),
                    i_ECLK=ClockSignal("fast"),
                    i_RST=ResetSignal(),
                    **{f"i_RDPNTR{i}": readptr[i] for i in range(len(readptr))},
                    **{f"i_WRPNTR{i}": writeptr[i] for i in range(len(writeptr))},
                    o_Q0=self.phy.dq.i[i+24],
                    o_Q1=self.phy.dq.i[i+16],
                    o_Q2=self.phy.dq.i[i+8],
                    o_Q3=self.phy.dq.i[i],
                ),
            ]

        return m
