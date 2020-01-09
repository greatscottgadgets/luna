#
# This file is part of LUNA.
#
""" SPI and derived interfaces. """

import unittest

from nmigen import *
from nmigen.back.pysim import Simulator

from ..util import rising_edge_detector, falling_edge_detector
from ..test.utils import LunaGatewareTestCase, sync_test_case

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


class SPIRegisterInterface(Elaboratable):
    """ SPI device interface that allows for register reads and writes via SPI.
    The SPI transaction format matches:

        in:  WAAAAAAA[...] VVVVVVVV[...]
        out: XXXXXXXX[...] RRRRRRRR[...]

    Where:
        W = write bit; a '1' indicates that the provided value is a write request
        A = all bits of the address
        V = value to be written into the register, if W is set
        R = value to be read from the register

    I/O signals:
        I: sck           -- SPI clock, from the SPI master
        I: sdi           -- SPI data in
        O: sdo           -- SPI data out
        I: cs            -- chip select, active high (as we assume your I/O will use PinsN)

    Other I/O ports are added dynamically with add_register().
    """

    def __init__(self, address_size=15, register_size=32, default_read_value=0, support_size_autonegotiation=True):
        """ 
        Parameters:
            address_size       -- the size of an address, in bits; recommended to be one bit
                                  less than a binary number, as the write command is formed by adding a one-bit
                                  write flag to the start of every address
            register_size      -- The size of any given register, in bits.
            default_read_value -- The read value read from a non-existent or write-only register.

            support_size_autonegotiation -- 
                If set, register 0 is used as a size auto-negotation register. Functionally equivalent to
                calling .support_size_autonegotation(); see its documentation for details on autonegtoation.
        """

        self.address_size  = address_size
        self.register_size = register_size
        self.default_read_value  = default_read_value

        #
        # I/O port
        #

        # Create our SPI I/O.
        self.sck = Signal()
        self.sdi = Signal()
        self.sdo = Signal()
        self.cs  = Signal()

        #
        # Internal details.
        #

        # Instantiate an SPI command transciever submodule.
        self.interface = SPICommandInterface(command_size=address_size + 1, word_size=register_size) 

        # Create a new, empty dictionary mapping registers to their signals.
        self.registers = {}

        # Create signals for each of our register control signals.
        self._is_write = Signal()
        self._address  = Signal(self.address_size)

        if support_size_autonegotiation:
            self.support_size_autonegotiation()


    def _ensure_register_is_unused(self, address):
        """ Checks to make sure a register address isn't in use before issuing it. """

        if address in self.registers:
            raise ValueError("can't add more than one register with address 0x{:x}!".format(address))


    def support_size_autonegotiation(self):
        """ Support autonegotiation of register and address size. Consumes address 0.
        
        Auto-negotation of size is relatively simple: the host sends a string of zeroes over
        the SPI bus, and we respond with:

            -- as many zeroes as there are address bits
            -- as many ones as there are data bits
            -- zeroes for any bits after

        In practice, this is functionally identical to setting register zero to a constant of all 1's.
        """
        self.add_read_only_register(0, read=-1)


    def add_sfr(self, address, *, read=None, write_signal=None, write_strobe=None, read_strobe=None):
        """ Adds a special function register to the given command interface.
        
        Parameters: 
            address       -- the register's address, as a big-endian integer
            read          -- a Signal or integer constant representing the 
                             value to be read at the given address; if not provided, the default
                             value will be read
            read_strobe   -- a Signal that is asserted when a read is completed; if not provided,
                             the relevant strobe will be left unconnected
            write_signal  -- a Signal set to the value to be written when a write is requested;
                             if not provided, writes will be ignored
            wrote_strobe  -- a Signal that goes high when a value is available for a write request
         """

        assert address < (2 ** self.address_size)
        self._ensure_register_is_unused(address)

        # Add the register to our collection.
        self.registers[address] = {
            'read': read,
            'write_signal': write_signal,
            'write_strobe': write_strobe,
            'read_strobe': read_strobe,
            'elaborate': None,
        }


    def add_read_only_register(self, address, *, read, read_strobe=None):
        """ Adds a read-only register.
        
        Parameters: 
            address       -- the register's address, as a big-endian integer
            read          -- a Signal or integer constant representing the 
                             value to be read at the given address; if not provided, the default
                             value will be read
            read_strobe   -- a Signal that is asserted when a read is completed; if not provided,
                             the relevant strobe will be left unconnected
        """
        self.add_sfr(address, read=read, read_strobe=read_strobe)



    def add_register(self, address, *, value_signal=None, size=None, name=None, read_strobe=None,
        write_strobe=None, reset=0):
        """ Adds a standard, memory-backed register. 
        
            Parameters: 
                address       -- the register's address, as a big-endian integer
                value_signal  -- the signal that will store the register's value; if omitted
                                 a storage register will be created automatically
                size          -- if value_signal isn't provided, this sets the size of the created register
                reset         -- if value_signal isn't provided, this sets the reset value of the created register
                read_strobe   -- a Signal to be asserted when the register is read; ignored if not provided
                write_strobe  -- a Signal to be asserted when the register is written; ignored if not provided

            Returns:
                value_signal  -- a signal that stores the register's value; which may be the value_signal arg,
                                 or may be a signal created during execution
        """
        self._ensure_register_is_unused(address)

        # Generate a name for the register, if we don't already have one.
        name = name if name else "register_{:x}".format(address)

        # Generate a backing store for the register, if we don't already have one.
        if value_signal is None:
            size = self.register_size if (size is None) else size
            value_signal = Signal(size, name=name, reset=reset)

        # If we don't have a write strobe signal, create an internal one.
        if write_strobe is None:
            write_strobe = Signal(name=name + "_write_strobe")

        # Create our register-value-input and our write strobe.
        write_value  = Signal.like(value_signal, name=name + "_write_value")

        # Create a generator for a the fragments that will manage the register's memory.
        def _elaborate_memory_register(m):
            with m.If(write_strobe):
                m.d.sync += value_signal.eq(write_value)

        # Add the register to our collection.
        self.registers[address] = {
            'read': value_signal,
            'write_signal': write_value,
            'write_strobe': write_strobe,
            'read_strobe': read_strobe,
            'elaborate': _elaborate_memory_register,
        }

        return value_signal


    def _elaborate_register(self, m, register_address, connections):
        """ Generates the hardware connections that handle a given register. """

        #
        # Elaborate our register hardware.
        #

        # Create a signal that goes high iff the given register is selected.
        register_selected = Signal(name="register_address_matches_{:x}".format(register_address))
        m.d.comb += register_selected.eq(self._address == register_address)

        # Our write signal is always connected to word_received; but it's only meaningful
        # when write_strobe is asserted.
        if connections['write_signal'] is not None:
            m.d.comb += connections['write_signal'].eq(self.interface.word_received)

        # If we have a write strobe, assert it iff:
        #  - this register is selected
        #  - the relevant command is a write command
        #  - we've just finished receiving the command's argument
        if connections['write_strobe'] is not None:
            m.d.comb += [
                connections['write_strobe'].eq(self._is_write & self.interface.word_complete & register_selected)
            ]

        # Create essentially the same connection with the read strobe.
        if connections['read_strobe'] is not None:
            m.d.comb += [
                connections['write_strobe'].eq(~self._is_write & self.interface.word_complete & register_selected)
            ]

        # If we have any additional code that assists in elaborating this register, run it.
        if connections['elaborate']:
            connections['elaborate'](m)


    def elaborate(self, platform):
        m = Module()

        # Connect up our SPI transceiver submodule.
        m.submodules.interface = self.interface
        m.d.comb += [
            self.interface.sck .eq(self.sck),
            self.interface.sdi .eq(self.sdi),
            self.sdo           .eq(self.interface.sdo),
            self.interface.cs  .eq(self.cs),
        ]

        # Split the command into our "write" and "address" signals.
        m.d.comb += [
            self._is_write.eq(self.interface.command[-1]),
            self._address .eq(self.interface.command[0:-1])
        ]

        # Create the control/write logic for each of our registers.
        for address, connections in self.registers.items():
            self._elaborate_register(m, address, connections)


        # Build the logic to select the 'to_send' value, which is selected
        # from all of our registers according to the selected register address.
        for address, connections in self.registers.items():

            first_item = True
            for address, connections in self.registers.items():
                statement = m.If if first_item else m.Elif

                with statement(self._address == address):

                    # Hook up the word-to-send signal either to the read value for the relevant
                    # register, or to the default read value.
                    if connections['read'] is not None:
                        m.d.comb += self.interface.word_to_send.eq(connections['read'])
                    else:
                        m.d.comb += self.interface.word_to_send.eq(self.default_read_value)

                # We've already created the m.If; from now on, use m.Elif
                first_item = False

        # Finally, tie all non-handled register values to always respond with the default.
        with m.Else():
            m.d.comb += self.interface.word_to_send.eq(self.default_read_value)

        return m


class SPIRegisterInterfaceTest(LunaGatewareTestCase):
    """ Tests for the SPI command interface. """


    def spi_send_bit(self, bit):
        """ Sends a single bit over the SPI bus. """
        cycles_per_bit = 4

        # Apply the new bit...
        yield self.dut.sdi.eq(bit)
        yield from self.advance_cycles(cycles_per_bit)

        # Create a RE of our serial clock.
        yield self.dut.sck.eq(1)
        yield from self.advance_cycles(cycles_per_bit)

        # Read the data on the bus, and then create our falling edge.
        return_value = (yield self.dut.sdo)
        yield from self.advance_cycles(cycles_per_bit)

        yield self.dut.sck.eq(0)
        yield from self.advance_cycles(cycles_per_bit)

        return return_value


    def spi_exchange_byte(self, datum):
        """ Sends a by over the virtual SPI bus. """

        bits = "{:08b}".format(datum)
        data_received = ""

        # Send each of our bits...
        for bit in bits:
            received = yield from self.spi_send_bit(int(bit))
            data_received += '1' if received else '0'

        return int(data_received, 2)


    def spi_exchange_data(self, data):
        """ Sends a string of bytes over our virtual SPI bus. """

        yield self.dut.cs.eq(1)
        yield

        response = bytearray()

        for byte in data:
            response_byte = yield from self.spi_exchange_byte(byte)
            response.append(response_byte)

        yield self.dut.cs.eq(0)
        yield

        return response

    def instantiate_dut(self):

        self.write_strobe = Signal()

        # Create a register and sample dataset to work with.
        dut = SPIRegisterInterface(default_read_value=0xDEADBEEF)
        dut.add_register(2, write_strobe=self.write_strobe)

        return dut


    def initialize_signals(self):
        # Start off with our clock low and the transaction idle.
        yield self.dut.sck.eq(0)
        yield self.dut.cs.eq(0)


    @sync_test_case
    def test_undefined_read_behavior(self):
        data = yield from self.spi_exchange_data([0, 1, 0, 0, 0, 0])
        self.assertEqual(bytes(data), b"\x00\x00\xde\xad\xbe\xef")

    @sync_test_case
    def test_write_behavior(self):

        # Send a write command...
        data = yield from self.spi_exchange_data(b"\x80\x02\x12\x34\x56\x78")
        self.assertEqual(bytes(data), b"\x00\x00\x00\x00\x00\x00")

        # ... and then read the relevant data back.
        data = yield from self.spi_exchange_data(b"\x00\x02\x12\x34\x56\x78")
        self.assertEqual(bytes(data), b"\x00\x00\x12\x34\x56\x78")



if __name__ == "__main__":
    unittest.main()
