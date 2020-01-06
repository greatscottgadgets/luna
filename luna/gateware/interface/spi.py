#
# This file is part of LUNA.
#
""" SPI and derived interfaces. """

from nmigen import *
from nmigen.cli import main
from nmigen.back.pysim import Simulator

from ..util import rising_edge_detector, falling_edge_detector


class SPIDeviceInterface(Elaboratable):
    """ Simple word-oriented SPI interface.
    
    I/O signals:
        I: sck           -- SPI clock, from the SPI master
        I: sdi           -- SPI data in
        O: sdo           -- SPI data out
        I: cs            -- chip select, active high (as we assume your I/O will use PinsN)

        O: word_in       -- the most recent word received
        O: word_complete -- strobe indicating a new word is present on word_in
        I: word_out      -- the word to be loaded; latched in on next word_complete and while cs is low
    """

    def __init__(self, *, word_size=8, clock_polarity=0, clock_phase=0):

        self.word_size      = word_size
        self.clock_polarity = clock_polarity
        self.clock_phase    = clock_phase

        #
        # I/O port.
        #

        # SPI
        self.sck            = Signal()
        self.sdi            = Signal()
        self.sdo            = Signal()
        self.cs             = Signal()

        # Data I/O
        self.word_in        = Signal(self.word_size)
        self.word_out       = Signal(self.word_size)
        self.word_complete  = Signal()


    def spi_edge_detectors(self, m):
        """ Generates edge detectors for the sample and output clocks, based on the current SPI mode. 
        
        Returns:
            sample_edge, output_edge -- signals that pulse high for a single cycle when we should
                                        sample and change our outputs, respectively
        """

        # Select whether we're working with an inverted or un-inverted serial clock.
        serial_clock = Signal()
        if self.clock_polarity:
            m.d.comb += serial_clock.eq(~self.sck)
        else:
            m.d.comb += serial_clock.eq(self.sck)

        # Generate the leading and trailing edge detectors.
        # Note that we use rising and falling edge detectors, but call these leading and
        # trailing edges, as our clock here may have been inverted.
        leading_edge  = rising_edge_detector(m, serial_clock)
        trailing_edge = falling_edge_detector(m, serial_clock)

        # Determine the sample and output edges based on the SPI clock phase.
        sample_edge = trailing_edge if self.clock_phase else leading_edge
        output_edge = leading_edge if self.clock_phase else trailing_edge

        return sample_edge, output_edge


    def elaborate(self, platform):
        m = Module()

        # Grab signals that detect when we should shift in and out.
        sample_edge, output_edge = self.spi_edge_detectors(m)

        # We'll use separate buffers for transmit and receive,
        # as this makes the code a little more readable.
        bit_count    = Signal(range(0, self.word_size), reset=0)
        current_tx   = Signal.like(self.word_out)
        current_rx   = Signal.like(self.word_in)

        # De-assert our control signals unless explicitly asserted.
        m.d.sync += self.word_complete.eq(0)

        # If the chip is selected, process our I/O:
        with m.If(self.cs):

            # Shift in data on each sample edge.
            with m.If(sample_edge):
                m.d.sync += [
                    current_rx.eq(Cat(current_rx[1:], self.sdi)),
                    bit_count.eq(bit_count + 1)
                ]

                # If we're just completing a word, handle I/O.
                with m.If(bit_count + 1 == self.word_size):
                    m.d.sync += [
                        self.word_complete .eq(1),
                        self.word_in       .eq(current_rx),
                        current_tx         .eq(self.word_out)
                    ]

            # Shift out data on each output edge.
            with m.If(output_edge):
                m.d.sync += [
                    self.sdo.eq(current_tx[-1]),
                    current_tx.eq(current_tx << 1),
                ]

        with m.Else():
            m.d.sync += current_tx.eq(self.word_out)
            m.d.sync += bit_count.eq(0)

        return m



class SPICommandInterface(Elaboratable):
    """ Variant of an SPIDeviceInterface that accepts command-prefixed data.

    I/O signals:
        I: sck           -- SPI clock, from the SPI master
        I: sdi           -- SPI data in
        O: sdo           -- SPI data out
        I: cs            -- chip select, active high (as we assume your I/O will use PinsN)

        O: command       -- the command read from the SPI bus
        O: command_ready -- a new command is ready

        O: word_received -- the most recent word received
        O: word_complete -- strobe indicating a new word is present on word_in
        I: word_to_send  -- the word to be loaded; latched in on next word_complete and while cs is low

    """

    def __init__(self, command_size=8, word_size=32):

        self.command_size = command_size
        self.word_size    = word_size

        #
        # I/O port.
        #

        # SPI
        self.sck            = Signal()
        self.sdi            = Signal()
        self.sdo            = Signal()
        self.cs             = Signal()

        # Command I/O.
        self.command        = Signal(self.command_size)
        self.command_ready  = Signal()

        # Data I/O
        self.word_received  = Signal(self.word_size)
        self.word_to_send   = Signal.like(self.word_received)
        self.word_complete  = Signal()


    def elaborate(self, platform):

        m = Module()
        sample_edge = falling_edge_detector(m, self.sck)

        # Bit counter: counts the number of bits received.
        max_bit_count = max(self.word_size, self.command_size)
        bit_count = Signal(range(0, max_bit_count + 1))

        # Shift registers for our command and data.
        current_command = Signal.like(self.command)
        current_word    = Signal.like(self.word_received)

        # De-assert our control signals unless explicitly asserted.
        m.d.sync += [
            self.command_ready.eq(0),
            self.word_complete.eq(0)
        ]

        with m.FSM():

            # STALL: entered when we can't accept new bits -- either when
            # CS starts asserted, or when we've received more data than expected.
            with m.State("STALL"):

                # Wait for CS to clear.
                with m.If(~self.cs):
                    m.next = 'IDLE'


            # We ignore all data until chip select is asserted, as that data Isn't For Us (TM).
            # We'll spin and do nothing until the bus-master addresses us.
            with m.State('IDLE'):
                m.d.sync += bit_count.eq(0)

                with m.If(self.cs):
                    m.next = 'RECEIVE_COMMAND'


            # Once CS is low, we'll shift in our command.
            with m.State('RECEIVE_COMMAND'):

                # Continue shifting in data until we have a full command.
                with m.If(bit_count < self.command_size):
                    with m.If(sample_edge):
                        m.d.sync += [
                            bit_count       .eq(bit_count + 1),
                            current_command .eq(Cat(self.sdi, current_command[:-1]))
                        ]

                # ... and then pass that command out to our controller.
                with m.Else():
                    m.d.sync += [
                        bit_count          .eq(0),
                        self.command_ready .eq(1),
                        self.command       .eq(current_command)
                    ]
                    m.next = 'PROCESSING'


            # Give our controller a wait state to prepare any response they might want to...
            with m.State('PROCESSING'):
                m.next = 'LATCH_OUTPUT'


            # ... and then latch in the response to transmit.
            with m.State('LATCH_OUTPUT'):
                m.d.sync += current_word.eq(self.word_to_send)
                m.next = 'SHIFT_DATA'


            # Finally, exchange data.
            with m.State('SHIFT_DATA'):
                m.d.sync += self.sdo.eq(current_word[-1])

                # Continue shifting data until we have a full word.
                with m.If(bit_count < self.word_size):
                    with m.If(sample_edge):
                        m.d.sync += [
                            bit_count    .eq(bit_count + 1),
                            current_word .eq(Cat(self.sdi, current_word[:-1]))
                        ]

                # ... and then output that word on our bus.
                with m.Else():
                    m.d.sync += [
                        bit_count          .eq(0),
                        self.word_complete .eq(1),
                        self.word_received .eq(current_word)
                    ]

                    # Stay in the stall state until CS is de-asserted.
                    m.next = 'STALL'

        return m
