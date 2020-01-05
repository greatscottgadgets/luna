#
# This file is part of LUNA.
#
""" SPI and derived interfaces. """

from nmigen import *
from nmigen.cli import main
from nmigen.back.pysim import Simulator

from ..util import rising_edge_detector

class SPICommandInterface(Elaboratable):
    """ 
    Simple SPI-based register interface; currently designed for a reduced SPI bus with no chip-select line.
    """

    def __init__(self, *, command_size=8, word_size=32):
        """ Parameters:

        command_size -- The size of each command word, in bits.
        word_size    -- The size of the data for each command.
        """

        self.command_size = command_size
        self.word_size    = word_size

        #
        # I/O port.
        #

        # SPI
        self.sck = Signal()
        self.sdi = Signal()
        self.sdo = Signal()

        # Control inputs.
        self.word_to_output    = Signal(word_size)

        # Control outputs.
        self.word_received     = Signal(word_size)
        self.command           = Signal(command_size)
        self.command_ready     = Signal()
        self.receive_complete  = Signal() 


    def elaborate(self, platform):
        m = Module()

        # Detect SCK edges.
        sck_edge = rising_edge_detector(m, self.sck)

        # Keep count of how many bits we've received.
        max_bit_count = max(self.command_size, self.word_size)
        bit_count = Signal(range(0, max_bit_count + 1), reset=0)

        # Default our control signals to un-asserted.
        m.d.sync += self.command_ready.eq(0)
        m.d.sync += self.receive_complete.eq(0)

        # Keep track of the current command and received words.
        current_command = Signal.like(self.command)
        current_word    = Signal(self.word_size + 1)

        with m.FSM():

            # We'll start off by receiving a command, bit by bit.
            with m.State("RECEIVE_COMMAND"):

                # Shift in our data on each SCK edge.
                with m.If(sck_edge):
                    m.d.sync +=  [
                        bit_count      .eq(bit_count + 1),
                        current_command.eq(Cat(self.sdi, current_command[:-1]))
                    ]
                
                # Once we've received a full command word, pass the command to the external controller,
                # and give the external controller time to respond to it.
                with m.If(bit_count == self.command_size):
                    m.next = 'PROCESSING'
                    m.d.sync += [
                        self.command_ready.eq(1),
                        self.command.eq(current_command)
                    ]

            # Give the external controller a wait state to handle the command and prepare a response.
            with m.State("PROCESSING"):
                m.d.sync += bit_count.eq(0)
                m.next = 'LATCH_RESPONSE'

            # Latch in any response provided by the external controller.
            with m.State("LATCH_RESPONSE"):
                m.d.sync += current_word.eq(self.word_to_output)
                m.next = 'EXCHANGE_DATA'

            # Transmit and receive data.
            with m.State('EXCHANGE_DATA'):

                # Shift out the least of our data bits.
                m.d.sync += self.sdo.eq(current_word[-1])

                # Shift in our data on each SCK edge.
                with m.If(sck_edge):
                    m.d.sync +=  [
                        bit_count   .eq(bit_count + 1),
                        current_word.eq(Cat(self.sdi, current_word[:-1]))
                    ]
                
                # Once we've exchanged a full word, latch our output,
                # and end the transaction.
                # controller to prepare a response.
                with m.If(bit_count == self.word_size):
                    m.next = 'RECEIVE_COMMAND'
                    m.d.sync += [
                        bit_count.eq(0),
                        self.word_received.eq(current_word),
                        self.receive_complete.eq(1)
                    ]

        return m


def _test_command_interface():
    """ Tests the SPI command interface. """

    ri = SPICommandInterface()

    # Simulate the relevant design.
    sim = Simulator(ri)
    sim.add_clock(1e-6)

    def wait(cycles):
        for _ in range(cycles):
            yield

    def shift_bit(sdi):
        yield ri.sck.eq(0)
        yield from wait(4)
        yield ri.sdi.eq(sdi)
        yield from wait(4)
        yield ri.sck.eq(1)
        yield from wait(4)

    def data_exchange():
        yield ri.word_to_output.eq(0xC001C0DE)

        shift_in = list("{:040b}".format(0xABDEADBEEF))
        response = 0

        while(shift_in):

            # Shift in the relevant data...
            sdi = int(shift_in.pop(0))
            yield from shift_bit(sdi)

            # ... and gather bits of the response.
            response = (response << 1) | (yield ri.sdo)

        assert (yield ri.command) == 0xAB
        assert (yield ri.word_received) == 0xDEADBEEF
        assert response == 0xC001C0DE

    sim.add_sync_process(data_exchange)
    sim.run()


#
# Self-test.
#
if __name__ == "__main__":
    _test_command_interface()
    print("All tests passed!\n")
