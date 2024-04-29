#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test.utils import LunaGatewareTestCase, usb_domain_test_case

from amaranth import Record
from luna.gateware.interface.ulpi import ULPIControlTranslator, ULPIRegisterWindow, ULPIRxEventDecoder, ULPITransmitTranslator

class TestULPIRegisters(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = ULPIRegisterWindow

    USB_CLOCK_FREQUENCY = 60e6
    SYNC_CLOCK_FREQUENCY = None

    def initialize_signals(self):
        yield self.dut.ulpi_dir.eq(0)

        yield self.dut.read_request.eq(0)
        yield self.dut.write_request.eq(0)


    @usb_domain_test_case
    def test_idle_behavior(self):
        """ Ensure we apply a NOP whenever we're not actively performing a command. """
        self.assertEqual((yield self.dut.ulpi_data_out), 0)


    @usb_domain_test_case
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


    @usb_domain_test_case
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


    @usb_domain_test_case
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


class ULPIRxEventDecoderTest(LunaGatewareTestCase):

    USB_CLOCK_FREQUENCY = 60e6
    SYNC_CLOCK_FREQUENCY = None

    def instantiate_dut(self):

        self.ulpi = Record([
            ("dir", [
                ("i", 1),
            ]),
            ("nxt", [
                ("i", 1),
            ]),
            ("data", [
                ("i", 8),
            ])
        ])

        return ULPIRxEventDecoder(ulpi_bus=self.ulpi)


    def initialize_signals(self):
        yield self.ulpi.dir.i.eq(0)
        yield self.ulpi.nxt.i.eq(0)
        yield self.ulpi.data.i.eq(0)
        yield self.dut.register_operation_in_progress.eq(0)


    @usb_domain_test_case
    def test_decode(self):

        # Provide a test value.
        yield self.ulpi.data.i.eq(0xAB)

        # First, set DIR and NXT at the same time, and verify that we
        # don't register an RxEvent.
        yield self.ulpi.dir.i.eq(1)
        yield self.ulpi.nxt.i.eq(1)

        yield from self.advance_cycles(5)
        self.assertEqual((yield self.dut.last_rx_command), 0x00)

        # Nothing should change when we drop DIR and NXT.
        yield self.ulpi.dir.i.eq(0)
        yield self.ulpi.nxt.i.eq(0)
        yield
        self.assertEqual((yield self.dut.last_rx_command), 0x00)


        # Setting DIR but not NXT should trigger an RxEvent; but not
        # until one cycle of "bus turnaround" has passed.
        yield self.ulpi.dir.i.eq(1)

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


class ControlTranslatorTest(LunaGatewareTestCase):

    USB_CLOCK_FREQUENCY = 60e6
    SYNC_CLOCK_FREQUENCY = None

    def instantiate_dut(self):
        self.reg_window = ULPIRegisterWindow()
        return ULPIControlTranslator(register_window=self.reg_window, own_register_window=True)


    def initialize_signals(self):
        dut = self.dut

        # Initialize our register signals to their default values.
        yield dut.xcvr_select.eq(1)
        yield dut.dm_pulldown.eq(1)
        yield dut.dp_pulldown.eq(1)
        yield dut.use_external_vbus_indicator.eq(0)
        yield dut.bus_idle.eq(1)


    @usb_domain_test_case
    def test_multiwrite_behavior(self):

        # Give our initialization some time to settle,
        # and verify that we haven't initiated anyting in that interim.
        yield from self.advance_cycles(10)
        self.assertEqual((yield self.reg_window.write_request), 0)

        # Change signals that span two registers.
        yield self.dut.op_mode.eq(0b11)
        yield self.dut.dp_pulldown.eq(0)
        yield self.dut.dm_pulldown.eq(0)
        yield
        yield

        # Once we've changed these, we should start trying to apply
        # our new value to the function control register.
        self.assertEqual((yield self.reg_window.address),      0x04)
        self.assertEqual((yield self.reg_window.write_data),   0b01011001)

        # which should occur until the data and address are accepted.
        yield self.reg_window.ulpi_next.eq(1)
        yield from self.wait_until(self.reg_window.done, timeout=10)
        yield
        yield

        # We should then experience a write to the function control register.
        self.assertEqual((yield self.reg_window.address),      0x0A)
        self.assertEqual((yield self.reg_window.write_data),   0b00000000)

        # Wait for that action to complete..
        yield self.reg_window.ulpi_next.eq(1)
        yield from self.wait_until(self.reg_window.done, timeout=10)
        yield
        yield

        # After which we shouldn't be trying to write anything at all.
        self.assertEqual((yield self.reg_window.address),       0)
        self.assertEqual((yield self.reg_window.write_data),    0)
        self.assertEqual((yield self.reg_window.write_request), 0)


class ULPITransmitTranslatorTest(LunaGatewareTestCase):
    USB_CLOCK_FREQUENCY=60e6
    SYNC_CLOCK_FREQUENCY=None

    FRAGMENT_UNDER_TEST = ULPITransmitTranslator

    def initialize_signals(self):
        yield self.dut.bus_idle.eq(1)

    @usb_domain_test_case
    def test_simple_transmit(self):
        dut = self.dut

        # We shouldn't try to transmit until we have a transmit request.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.ulpi_out_req), 0)

        # Present a simple SOF PID.
        yield dut.tx_valid.eq(1)
        yield dut.tx_data.eq(0xA5)
        yield

        # Our PID should have been translated into a transmit request, with
        # our PID in the lower nibble.
        self.assertEqual((yield dut.ulpi_data_out), 0b01000101)
        self.assertEqual((yield dut.tx_ready),      0)
        self.assertEqual((yield dut.ulpi_stp),      0)
        yield
        self.assertEqual((yield dut.ulpi_out_req),  1)

        # Our PID should remain there until we indicate we're ready.
        self.advance_cycles(10)
        self.assertEqual((yield dut.ulpi_data_out), 0b01000101)

        # Once we're ready, we should accept the data from the link and continue.
        yield dut.ulpi_nxt.eq(1)
        yield
        self.assertEqual((yield dut.tx_ready),      1)
        yield dut.tx_data.eq(0x11)
        yield

        # At which point we should present the relevant data directly.
        yield
        self.assertEqual((yield dut.ulpi_data_out), 0x11)

        # Finally, once we stop our transaction...
        yield dut.tx_valid.eq(0)
        yield

        # ... we should get a cycle of STP.
        self.assertEqual((yield dut.ulpi_data_out), 0)
        self.assertEqual((yield dut.ulpi_stp),      1)

        # ... followed by idle.
        yield
        self.assertEqual((yield dut.ulpi_stp),      0)


    @usb_domain_test_case
    def test_handshake(self):
        dut = self.dut

        # Present a simple ACK PID.
        yield dut.tx_valid.eq(1)
        yield dut.tx_data.eq(0b11010010)
        yield

        # Our PID should have been translated into a transmit request, with
        # our PID in the lower nibble.
        self.assertEqual((yield dut.ulpi_data_out), 0b01000010)
        self.assertEqual((yield dut.tx_ready),      0)
        self.assertEqual((yield dut.ulpi_stp),      0)

        # Once the PHY accepts the data, it'll assert NXT.
        yield dut.ulpi_nxt.eq(1)
        yield
        self.assertEqual((yield dut.ulpi_out_req),  1)

        # ... which will trigger the transmitter to drop tx_valid.
        yield dut.tx_valid.eq(0)

        # ... we should get a cycle of STP.
        yield
        #self.assertEqual((yield dut.ulpi_data_out), 0)
        #self.assertEqual((yield dut.ulpi_stp),      1)

        # ... followed by idle.
        yield
        self.assertEqual((yield dut.ulpi_stp),      0)

