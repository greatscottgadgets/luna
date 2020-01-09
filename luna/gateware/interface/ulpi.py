#
# This file is part of LUNA.
#
""" ULPI interfacing hardware. """

from nmigen import Signal, Module, Cat, Elaboratable

import unittest
from nmigen.back.pysim import Simulator

from ..test.utils import LunaGatewareTestCase, sync_test_case


class PHYResetController(Elaboratable):
    """ Gateware that implements a short power-on-reset pulse to reset an attached PHY.
    
    I/O ports:

        I: trigger   -- A signal that triggers a reset when high.
        O: phy_reset -- The signal to be delivered to the target PHY.
    """

    def __init__(self, *, clock_frequency=60e6, reset_length=2e-6, power_on_reset=True):
        """ Params:

            reset_length   -- The length of a reset pulse, in seconds.
            power_on_reset -- If True or omitted, the reset will be applied once the firmware
                            is configured.
        """

        from math import ceil

        self.power_on_reset = power_on_reset

        # Compute the reset length in cycles.
        clock_period = 1 / clock_frequency
        self.reset_length_cycles = ceil(reset_length / clock_period)

        #
        # I/O port
        #
        self.trigger   = Signal()
        self.phy_reset = Signal()


    def elaborate(self, platform):
        m = Module()

        # Counter that stores how many cycles we've spent in reset.
        cycles_in_reset = Signal(range(0, self.reset_length_cycles))

        reset_state = 'RESETTING' if self.power_on_reset else 'IDLE'
        with m.FSM(reset=reset_state) as fsm:

            # Drive the PHY reset whenever we're in the RESETTING cycle.
            m.d.comb += self.phy_reset.eq(fsm.ongoing('RESETTING'))

            with m.State('IDLE'):
                m.d.sync += cycles_in_reset.eq(0)

                # Wait for a reset request.
                with m.If(self.trigger):
                    m.next = 'RESETTING'

            with m.State('RESETTING'):
                m.d.sync += cycles_in_reset.eq(cycles_in_reset + 1)

                with m.If(cycles_in_reset + 1 == self.reset_length_cycles):
                    m.next = 'IDLE'

        return m


class PHYResetControllerTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = PHYResetController
   
    def initialize_signals(self):
        yield self.dut.trigger.eq(0)


    @sync_test_case
    def test_power_on_reset(self):

        #
        # After power-on, the PHY should remain in reset for a while.
        #
        yield
        self.assertEqual((yield self.dut.phy_reset), 1)

        yield from self.advance_cycles(30)
        self.assertEqual((yield self.dut.phy_reset), 1)

        yield from self.advance_cycles(60)
        self.assertEqual((yield self.dut.phy_reset), 1)

        #
        # Then, after the relevant reset time, it should resume being unasserted.
        #
        yield from self.advance_cycles(30)
        self.assertEqual((yield self.dut.phy_reset), 0)



class ULPIRegisterWindow(Elaboratable):
    """ Gateware interface that handles ULPI register reads and writes.
    
    I/O ports:

        # ULPI signals:
        I: ulpi_data_in[8]   -- input value of the ULPI data lines
        O: ulpi_data_out[8]  -- output value of the ULPI data lines
        O: ulpi_out_en       -- true iff we're trying to drive the ULPI data lines

        # Controller signals:
        O: busy              -- indicates when the register window is busy processing a transaction 
        I: address[6]        -- the address of the register to work with
        O: done              -- strobe that indicates when a register request is complete

        I: read_request      -- strobe that requests a register read
        O: read_data[8]      -- data read from the relevant register read

        I: write_request     -- strobe that indicates a register write
        I: write_data[8]     -- data to be written during a register write

    """

    COMMAND_REG_READ = 0b11000000

    def __init__(self):

        #
        # I/O port.
        #

        self.ulpi_data_in  = Signal(8)
        self.ulpi_data_out = Signal(8, reset=0xff)
        self.ulpi_out_req  = Signal()
        self.ulpi_dir      = Signal()
        self.ulpi_next     = Signal()
        self.ulpi_stop     = Signal()

        self.busy          = Signal()
        self.address       = Signal(6)
        self.done          = Signal()

        self.read_request  = Signal()
        self.read_data     = Signal(8)

        self.write_request = Signal()
        self.write_data    = Signal(8)


    def elaborate(self, platform):
        m = Module()

        current_address = Signal(6)
        current_write   = Signal(8)

        # Keep our control signals low unless explicitly asserted.
        m.d.sync += [
            self.ulpi_out_req.eq(0),
            self.ulpi_stop   .eq(0),
            self.done        .eq(0)
        ]

        # Keep our command line at "NOP" when it's not being set.
        m.d.sync += self.ulpi_data_out.eq(0xFF)

        with m.FSM() as fsm:

            # We're busy whenever we're not IDLE; indicate so.
            m.d.comb += self.busy.eq(~fsm.ongoing('IDLE'))

            # IDLE: wait for a request to be made
            with m.State('IDLE'):

                # Constantly latch in our arguments while IDLE.
                # We'll stop latching these in as soon as we're busy.
                m.d.sync += [
                    current_address .eq(self.address),
                    current_write   .eq(self.write_data)
                ]

                with m.If(self.read_request):
                    m.next = 'START_READ'


            # START_READ: wait for the bus to be idle, so we can transmit.
            with m.State('START_READ'):

                # Wait for the bus to be idle.
                with m.If(~self.ulpi_dir):
                    m.next = 'SEND_READ_ADDRESS'

                    # Once it is, start sending our command.
                    m.d.sync += [
                        self.ulpi_data_out .eq(self.COMMAND_REG_READ | self.address),
                        self.ulpi_out_req  .eq(1)
                    ]


            # SEND_READ_ADDRESS: Request sending the read address, which we
            # start sending on the next clock cycle. Note that we don't want
            # to come into this state writing, as we need to lead with a
            # bus-turnaround cycle.
            with m.State('SEND_READ_ADDRESS'):

                # If DIR has become asserted, we're being interrupted. 
                # We'll have to restart the read after the interruption is over.
                with m.If(self.ulpi_dir):
                    m.next = 'START_READ'

                # If NXT becomes asserted without us being interrupted by
                # DIR, then the PHY has accepted the read. Release our write
                # request, so the next cycle can properly act as a bus turnaround.
                with m.If(self.ulpi_next):
                    m.d.sync += [
                        self.ulpi_out_req  .eq(0),
                        self.ulpi_data_out .eq(0xFF),
                    ]
                    m.next = 'READ_TURNAROUND'

                with m.Else():

                    # Start sending read command, which contains our address.
                    m.d.sync += [
                        self.ulpi_data_out .eq(self.COMMAND_REG_READ | self.address),
                        self.ulpi_out_req  .eq(1)
                    ]



            # READ_TURNAROUND: wait for the PHY to take control of the ULPI bus.
            with m.State('READ_TURNAROUND'):

                # After one cycle, we should have a data byte ready.
                m.next = 'READ_COMPLETE'


            # READ_COMPLETE: the ULPI read exchange is complete, and the read data is ready.
            with m.State('READ_COMPLETE'):
                m.next = 'IDLE'

                # Latch in the data, and indicate that we have new, valid data.
                m.d.sync += [
                    #self.read_data .eq(self.ulpi_data_in),
                    self.read_data .eq(self.ulpi_data_in),
                    self.done      .eq(1)
                ]

        return m



class TestULPIRegisters(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = ULPIRegisterWindow

    def initialize_signals(self):
        yield self.dut.ulpi_dir.eq(0)

        yield self.dut.read_request.eq(0)
        yield self.dut.write_request.eq(0)


    @sync_test_case
    def test_idle_behavior(self):

        # Ensure we apply a NOP whenever we're not actively performing a command.
        self.assertEqual((yield self.dut.ulpi_data_out), 0xFF)


    @sync_test_case
    def test_register_read(self):
        """ Validates a register read. """

        # Poison the register value with a fail value (0xBD).
        yield self.dut.ulpi_data_in.eq(0xBD)

        # Set up a read request.
        yield self.dut.address.eq(0)
        yield

        # After a read request, we should be busy...
        yield from self.pulse(self.dut.read_request)
        self.assertEqual((yield self.dut.busy), 1)

        # ... and then, since dir is unasserted, we should have a read command.
        yield
        self.assertEqual((yield self.dut.ulpi_data_out), 0b11000000)

        # We should continue to present the command...
        yield from self.advance_cycles(10)
        self.assertEqual((yield self.dut.ulpi_data_out), 0b11000000)
        self.assertEqual((yield self.dut.busy), 1)

        # ... until the host accepts it.
        yield self.dut.ulpi_next.eq(1)
        yield

        # We should then wait for a single bus turnaround cycle before reading.
        yield

        # And then should read whatever value is present.
        yield self.dut.ulpi_data_in.eq(0x07)
        yield
        yield
        self.assertEqual((yield self.dut.read_data), 0x07)

        # Finally, we should return to idle.
        self.assertEqual((yield self.dut.busy), 0)


if __name__ == "__main__":
    unittest.main()
