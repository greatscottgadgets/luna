#
# This file is part of LUNA.
#
""" ULPI interfacing hardware. """

from nmigen import Signal, Module, Cat, Elaboratable, ClockSignal, Record, ResetSignal

import unittest
from nmigen.back.pysim import Simulator
from ..test import LunaGatewareTestCase, ulpi_domain_test_case, sync_test_case



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

    COMMAND_REG_WRITE = 0b10000000
    COMMAND_REG_READ  = 0b11000000

    def __init__(self):

        #
        # I/O port.
        #

        self.ulpi_data_in  = Signal(8)
        self.ulpi_data_out = Signal(8)
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
        m.d.ulpi += [
            self.ulpi_out_req.eq(0),
            self.ulpi_stop   .eq(0),
            self.done        .eq(0)
        ]

        with m.FSM(domain='ulpi') as fsm:

            # We're busy whenever we're not IDLE; indicate so.
            m.d.comb += self.busy.eq(~fsm.ongoing('IDLE'))

            # IDLE: wait for a request to be made
            with m.State('IDLE'):

                # Apply a NOP whenever we're idle.
                #
                # This doesn't technically help for normal ULPI
                # operation, as the controller should handle this,
                # but it cleans up the output in our tests and allows
                # this unit to be used standalone.
                m.d.ulpi += self.ulpi_data_out.eq(0)

                # Constantly latch in our arguments while IDLE.
                # We'll stop latching these in as soon as we're busy.
                m.d.ulpi += [
                    current_address .eq(self.address),
                    current_write   .eq(self.write_data)
                ]

                with m.If(self.read_request):
                    m.next = 'START_READ'

                with m.If(self.write_request):
                    m.next = 'START_WRITE'

            #
            # Read handling.
            #

            # START_READ: wait for the bus to be idle, so we can transmit.
            with m.State('START_READ'):

                # Wait for the bus to be idle.
                with m.If(~self.ulpi_dir):
                    m.next = 'SEND_READ_ADDRESS'

                    # Once it is, start sending our command.
                    m.d.ulpi += [
                        self.ulpi_data_out .eq(self.COMMAND_REG_READ | self.address),
                        self.ulpi_out_req  .eq(1)
                    ]


            # SEND_READ_ADDRESS: Request sending the read address, which we
            # start sending on the next clock cycle. Note that we don't want
            # to come into this state writing, as we need to lead with a
            # bus-turnaround cycle.
            with m.State('SEND_READ_ADDRESS'):
                m.d.ulpi += self.ulpi_out_req.eq(1)

                # If DIR has become asserted, we're being interrupted.
                # We'll have to restart the read after the interruption is over.
                with m.If(self.ulpi_dir):
                    m.next = 'START_READ'
                    m.d.ulpi += self.ulpi_out_req.eq(0)

                # If NXT becomes asserted without us being interrupted by
                # DIR, then the PHY has accepted the read. Release our write
                # request, so the next cycle can properly act as a bus turnaround.
                with m.Elif(self.ulpi_next):
                    m.d.ulpi += [
                        self.ulpi_out_req  .eq(0),
                        self.ulpi_data_out .eq(0),
                    ]
                    m.next = 'READ_TURNAROUND'


            # READ_TURNAROUND: wait for the PHY to take control of the ULPI bus.
            with m.State('READ_TURNAROUND'):

                # After one cycle, we should have a data byte ready.
                m.next = 'READ_COMPLETE'


            # READ_COMPLETE: the ULPI read exchange is complete, and the read data is ready.
            with m.State('READ_COMPLETE'):
                m.next = 'IDLE'

                # Latch in the data, and indicate that we have new, valid data.
                m.d.ulpi += [
                    self.read_data .eq(self.ulpi_data_in),
                    self.done      .eq(1)
                ]

            #
            # Write handling.
            #

            # START_WRITE: wait for the bus to be idle, so we can transmit.
            with m.State('START_WRITE'):

                # Wait for the bus to be idle.
                with m.If(~self.ulpi_dir):
                    m.next = 'SEND_WRITE_ADDRESS'

                    # Once it is, start sending our command.
                    m.d.ulpi += [
                        self.ulpi_data_out .eq(self.COMMAND_REG_WRITE | self.address),
                        self.ulpi_out_req  .eq(1)
                    ]

            # SEND_WRITE_ADDRESS: Continue sending the write address until the
            # target device accepts it.
            with m.State('SEND_WRITE_ADDRESS'):
                m.d.ulpi += self.ulpi_out_req.eq(1)

                # If DIR has become asserted, we're being interrupted.
                # We'll have to restart the write after the interruption is over.
                with m.If(self.ulpi_dir):
                    m.next = 'START_WRITE'
                    m.d.ulpi += self.ulpi_out_req.eq(0)

                # Hold our address until the PHY has accepted the command;
                # and then move to presenting the PHY with the value to be written.
                with m.Elif(self.ulpi_next):
                    m.d.ulpi += self.ulpi_data_out.eq(self.write_data)
                    m.next = 'HOLD_WRITE'


            # Hold the write data on the bus until the device acknowledges it.
            with m.State('HOLD_WRITE'):
                m.d.ulpi += self.ulpi_out_req.eq(1)

                # Handle interruption.
                with m.If(self.ulpi_dir):
                    m.next = 'START_WRITE'
                    m.d.ulpi += self.ulpi_out_req.eq(0)

                # Hold the data present until the device has accepted it.
                # Once it has, pulse STP for a cycle to complete the transaction.
                with m.Elif(self.ulpi_next):
                    m.d.ulpi += [
                        self.ulpi_data_out.eq(0),
                        self.ulpi_out_req.eq(0),
                        self.ulpi_stop.eq(1)
                    ]
                    m.next = 'IDLE'

        return m



class TestULPIRegisters(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = ULPIRegisterWindow

    ULPI_CLOCK_FREQUENCY = 60e6
    SYNC_CLOCK_FREQUENCY = None

    def initialize_signals(self):
        yield self.dut.ulpi_dir.eq(0)

        yield self.dut.read_request.eq(0)
        yield self.dut.write_request.eq(0)


    @ulpi_domain_test_case
    def test_idle_behavior(self):
        """ Ensure we apply a NOP whenever we're not actively performing a command. """
        self.assertEqual((yield self.dut.ulpi_data_out), 0)


    @ulpi_domain_test_case
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


    @ulpi_domain_test_case
    def test_interrupted_read(self):
        """ Validates how a register read works when interrupted by a change in DIR. """

        # Set up a read request while DIR is asserted.
        yield self.dut.ulpi_dir.eq(1)
        yield self.dut.address.eq(0)
        yield from self.pulse(self.dut.read_request)

        # We shouldn't try to output anything until DIR is de-asserted.
        yield from self.advance_cycles(1)
        self.assertEqual((yield self.dut.ulpi_out_req), 0)
        yield from self.advance_cycles(10)
        self.assertEqual((yield self.dut.ulpi_out_req), 0)

        # De-assert DIR, and let the platform apply a read command.
        yield self.dut.ulpi_dir.eq(0)
        yield from self.advance_cycles(2)
        self.assertEqual((yield self.dut.ulpi_data_out), 0b11000000)

        # Assert DIR again; interrupting the read. This should bring
        # the platform back to its "waiting for the bus" state.
        yield self.dut.ulpi_dir.eq(1)
        yield from self.advance_cycles(2)
        self.assertEqual((yield self.dut.ulpi_out_req), 0)

        # Clear DIR, and validate that the device starts driving the command again
        yield self.dut.ulpi_dir.eq(0)
        yield from self.advance_cycles(2)
        self.assertEqual((yield self.dut.ulpi_data_out), 0b11000000)

        # Apply NXT so the read can finally continue.
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


    @ulpi_domain_test_case
    def test_register_write(self):

        # Set up a write request.
        yield self.dut.address.eq(0b10)
        yield self.dut.write_data.eq(0xBC)
        yield

        # Starting the request should make us busy.
        yield from self.pulse(self.dut.write_request)
        self.assertEqual((yield self.dut.busy), 1)

        # ... and then, since dir is unasserted, we should have a write command.
        yield
        self.assertEqual((yield self.dut.ulpi_data_out), 0b10000010)

        # We should continue to present the command...
        yield from self.advance_cycles(10)
        self.assertEqual((yield self.dut.ulpi_data_out), 0b10000010)
        self.assertEqual((yield self.dut.busy), 1)

        # ... until the host accepts it.
        yield self.dut.ulpi_next.eq(1)
        yield

        # We should then present the data to be written...
        yield self.dut.ulpi_next.eq(0)
        yield
        self.assertEqual((yield self.dut.ulpi_data_out), 0xBC)

        # ... and continue doing so until the host accepts it...
        yield from self.advance_cycles(10)
        self.assertEqual((yield self.dut.ulpi_data_out), 0xBC)

        yield self.dut.ulpi_next.eq(1)
        yield from self.advance_cycles(2)

        # ... at which point stop should be asserted for one cycle.
        self.assertEqual((yield self.dut.ulpi_stop), 1)
        yield

        # Finally, we should go idle.
        self.assertEqual((yield self.dut.ulpi_stop), 0)
        self.assertEqual((yield self.dut.busy), 0)


class ULPIRxEventDecoder(Elaboratable):
    """ Simple piece of gateware that tracks receive events.

    I/O port:

        I: ulpi_data_in[8] -- The current input state of the ULPI data lines.
        I: ulpi_dir        -- The ULPI bus-direction signal.
        I: ulpi_nxt        -- The ULPI 'next' throttle signal.
        I: register_operation_in_progress
            Signal that should be true iff we're performing a register operation.

        O: last_rx_command -- The full byte value of the last RxCmd.

        O: line_state[2]   -- The states of the two USB lines.
        O: rx_active       -- True when a packet receipt is active.
        O: rx_error        -- True when a packet recieve parse has occurred.
        O: host_disconnect -- True if the host has just disconnected.
        O: id_digital      -- Digital value of the ID pin.
        O: vbus_valid      -- True iff a valid VBUS voltage is present
        O: session_end     -- True iff a session has just ended.
    """

    def __init__(self, *, ulpi_bus):

        #
        # I/O port.
        #
        self.ulpi = ulpi_bus
        self.register_operation_in_progress = Signal()

        # Optional: signal that allows access to the last RxCmd byte.
        self.last_rx_command = Signal(8)

        self.line_state      = Signal(2)
        self.rx_active       = Signal()
        self.rx_error        = Signal()
        self.host_disconnect = Signal()
        self.id_digital      = Signal()
        self.vbus_valid      = Signal()
        self.session_end     = Signal()


    def elaborate(self, platform):
        m = Module()

        # An RxCmd is present when three conditions are met:
        # - We're not actively undergoing a register read.
        # - Direction has been high for more than one cycle.
        # - NXT is low.

        # To implement the first condition, we'll first create a delayed
        # version of DIR, and then logically AND it with the current value.
        direction_delayed = Signal()
        m.d.ulpi += direction_delayed.eq(self.ulpi.dir)

        receiving = Signal()
        m.d.comb += receiving.eq(direction_delayed & self.ulpi.dir)

        # Sample the DATA lines whenever these conditions are met.
        with m.If(receiving & ~self.ulpi.nxt & ~self.register_operation_in_progress):
            m.d.ulpi += self.last_rx_command.eq(self.ulpi.data.i)

        # Break the most recent RxCmd into its UMTI-equivalent signals.
        # From table 3.8.1.2 in the ULPI spec; rev 1.1/Oct-20-2004.
        m.d.comb += [
            self.line_state      .eq(self.last_rx_command[0:2]),
            self.vbus_valid      .eq(self.last_rx_command[2:4] == 0b11),
            self.session_end     .eq(self.last_rx_command[2:4] == 0b00),
            self.rx_active       .eq(self.last_rx_command[4]),
            self.rx_error        .eq(self.last_rx_command[4:6] == 0b11),
            self.host_disconnect .eq(self.last_rx_command[4:6] == 0b10),
            self.id_digital      .eq(self.last_rx_command[6]),
        ]

        return m


class ULPIRxEventDecoderTest(LunaGatewareTestCase):

    ULPI_CLOCK_FREQUENCY=60e6
    SYNC_CLOCK_FREQUENCY = None

    def instantiate_dut(self):

        self.ulpi = Record([
            ("dir", 1),
            ("nxt", 1),
            ("data", [
                ("i", 8),
            ])
        ])

        return ULPIRxEventDecoder(ulpi_bus=self.ulpi)


    def initialize_signals(self):
        yield self.ulpi.dir.eq(0)
        yield self.ulpi.nxt.eq(0)
        yield self.ulpi.data.i.eq(0)
        yield self.dut.register_operation_in_progress.eq(0)


    @ulpi_domain_test_case
    def test_decode(self):

        # Provide a test value.
        yield self.ulpi.data.i.eq(0xAB)

        # First, set DIR and NXT at the same time, and verify that we
        # don't register an RxEvent.
        yield self.ulpi.dir.eq(1)
        yield self.ulpi.nxt.eq(1)

        yield from self.advance_cycles(5)
        self.assertEqual((yield self.dut.last_rx_command), 0x00)

        # Nothing should change when we drop DIR and NXT.
        yield self.ulpi.dir.eq(0)
        yield self.ulpi.nxt.eq(0)
        yield
        self.assertEqual((yield self.dut.last_rx_command), 0x00)


        # Setting DIR but not NXT should trigger an RxEvent; but not
        # until one cycle of "bus turnaround" has passed.
        yield self.ulpi.dir.eq(1)

        yield self.ulpi.data.i.eq(0x12)
        yield
        self.assertEqual((yield self.dut.last_rx_command), 0x00)

        yield self.ulpi.data.i.eq(0b00011110)
        yield from self.advance_cycles(2)

        self.assertEqual((yield self.dut.last_rx_command), 0b00011110)

        # Validate that we're decoding this RxCommand correctly.
        self.assertEqual((yield self.dut.line_state),     0b10)
        self.assertEqual((yield self.dut.vbus_valid),        1)
        self.assertEqual((yield self.dut.rx_active),         1)
        self.assertEqual((yield self.dut.rx_error),          0)
        self.assertEqual((yield self.dut.host_disconnect),   0)



class UMTITranslator(Elaboratable):
    """ Gateware that translates a ULPI interface into a simpler UMTI one.

    I/O port:

        B: ulpi          -- ULPI bus / interface record
        O: busy          -- signal that's true iff the ULPI interface is being used
                            for a register or transmit command

        # Signals for diagnostic use:
        O: last_rxcmd    -- The byte content of the last RxCmd.

        I: address       -- The ULPI register address to work with.
        O: read_data[8]  -- The contents of the most recently read ULPI command.
        I: write_data[8] -- The data to be written on the next write request.
        I: manual_read   -- Strobe that triggers a diagnostic read.
        I: manual_write  -- Strobe that triggers a diagnostic write.

    """

    def __init__(self, *, ulpi):
        """ Params:

            ulpi -- The ULPI bus to communicate with.
        """

        #
        # I/O port
        #
        self.ulpi            = ulpi
        self.busy            = Signal()

        self.vbus_valid      = Signal()


        # Diagnostic I/O.
        self.last_rx_command = Signal(8)

        self.address         = Signal(6)
        self.read_data       = Signal(8)
        self.write_data      = Signal(8)
        self.manual_read     = Signal()
        self.manual_write    = Signal()


    def elaborate(self, platform):
        m = Module()

        # Create the component parts of our ULPI interfacing hardware.
        register_window = ULPIRegisterWindow()
        rxevent_decoder = ULPIRxEventDecoder(ulpi_bus=self.ulpi)
        m.submodules.register_window = register_window
        m.submodules.rxevent_decoder = rxevent_decoder

        # Connect our ULPI control signals to each of our subcomponents.
        m.d.comb += [

            # Drive the bus whenever the target PHY isn't.
            self.ulpi.data.oe            .eq(~self.ulpi.dir),

            # Generate our busy signal.
            self.busy                    .eq(register_window.busy),

            # Connect up our clock and reset signals.
            self.ulpi.clk                .eq(ClockSignal("ulpi")),
            self.ulpi.rst                .eq(ResetSignal("ulpi")),

            # Connect our data inputs to the event decoder.
            # Note that the event decoder is purely passive.
            rxevent_decoder.register_operation_in_progress.eq(register_window.busy),
            self.last_rx_command          .eq(rxevent_decoder.last_rx_command),

            self.vbus_valid               .eq(rxevent_decoder.vbus_valid),

            # Connect our signals to our register window.
            register_window.ulpi_data_in  .eq(self.ulpi.data.i),
            register_window.ulpi_dir      .eq(self.ulpi.dir),
            register_window.ulpi_next     .eq(self.ulpi.nxt),
            self.ulpi.data.o              .eq(register_window.ulpi_data_out),
            self.ulpi.stp                 .eq(register_window.ulpi_stop),

            register_window.address       .eq(self.address),
            register_window.write_data    .eq(self.write_data),
            register_window.read_request  .eq(self.manual_read),
            register_window.write_request .eq(self.manual_write),
            self.read_data                .eq(register_window.read_data)
        ]

        return m


if __name__ == "__main__":
    unittest.main()
