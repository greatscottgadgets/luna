#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test           import LunaGatewareTestCase, usb_domain_test_case

from amaranth import Record
from luna.gateware.usb.usb2.packet import USBDataPacketDeserializer, USBDataPacketGenerator, USBDataPacketReceiver
from luna.gateware.usb.usb2.packet import USBHandshakeDetector, USBHandshakeGenerator
from luna.gateware.usb.usb2.packet import InterpacketTimerInterface, USBInterpacketTimer, USBTokenDetector

class USBPacketizerTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY  = 60e6

    def instantiate_dut(self, extra_arguments=None):
        self.utmi = Record([
            ("rx_data",   8),
            ("rx_active", 1),
            ("rx_valid",  1)
        ])

        # If we don't have explicit extra arguments, use the base class's.
        if extra_arguments is None:
            extra_arguments = self.FRAGMENT_ARGUMENTS

        return self.FRAGMENT_UNDER_TEST(utmi=self.utmi, **extra_arguments)

    def provide_byte(self, byte):
        """ Provides a given byte on the UTMI receive data for one cycle. """
        yield self.utmi.rx_data.eq(byte)
        yield


    def start_packet(self, *, set_rx_valid=True):
        """ Starts a UTMI packet receive. """
        yield self.utmi.rx_active.eq(1)

        if set_rx_valid:
            yield self.utmi.rx_valid.eq(1)

        yield


    def end_packet(self):
        """ Starts a UTMI packet receive. """
        yield self.utmi.rx_active.eq(0)
        yield self.utmi.rx_valid.eq(0)
        yield


    def provide_packet(self, *octets, cycle_after=True):
        """ Provides an entire packet transaction at once; for convenience. """
        yield from self.start_packet()
        for b in octets:
            yield from self.provide_byte(b)
        yield from self.end_packet()

        if cycle_after:
            yield


class USBTokenDetectorTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBTokenDetector

    @usb_domain_test_case
    def test_valid_token(self):
        dut = self.dut

        # Assume our device is at address 0x3a.
        yield dut.address.eq(0x3a)

        # When idle, we should have no new-packet events.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.interface.new_frame), 0)
        self.assertEqual((yield dut.interface.new_token), 0)

        # From: https://usb.org/sites/default/files/crcdes.pdf
        # out to 0x3a, endpoint 0xa => 0xE1 5C BC
        yield from self.provide_packet(0b11100001, 0b00111010, 0b00111101)

        # Validate that we just finished a token.
        self.assertEqual((yield dut.interface.new_token), 1)
        self.assertEqual((yield dut.interface.new_frame), 0)

        # Validate that we got the expected PID.
        self.assertEqual((yield dut.interface.pid), 0b0001)

        # Validate that we got the expected address / endpoint.
        self.assertEqual((yield dut.interface.address),  0x3a)
        self.assertEqual((yield dut.interface.endpoint), 0xa )

        # Ensure that our strobe returns to 0, afterwards.
        yield
        self.assertEqual((yield dut.interface.new_token), 0)


    @usb_domain_test_case
    def test_valid_start_of_frame(self):
        dut = self.dut
        yield from self.provide_packet(0b10100101, 0b00111010, 0b00111101)

        # Validate that we just finished a token.
        self.assertEqual((yield dut.interface.new_token), 0)
        self.assertEqual((yield dut.interface.new_frame), 1)

        # Validate that we got the expected address / endpoint.
        self.assertEqual((yield dut.interface.frame), 0x53a)


    @usb_domain_test_case
    def test_token_to_other_device(self):
        dut = self.dut

        # Assume our device is at 0x1f.
        yield dut.address.eq(0x1f)

        # From: https://usb.org/sites/default/files/crcdes.pdf
        # out to 0x3a, endpoint 0xa => 0xE1 5C BC
        yield from self.provide_packet(0b11100001, 0b00111010, 0b00111101)

        # Validate that we did not count this as a token received,
        # as it wasn't for us.
        self.assertEqual((yield dut.interface.new_token), 0)


class USBHandshakeDetectorTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBHandshakeDetector

    @usb_domain_test_case
    def test_ack(self):
        yield from self.provide_packet(0b11010010)
        self.assertEqual((yield self.dut.detected.ack), 1)

    @usb_domain_test_case
    def test_nak(self):
        yield from self.provide_packet(0b01011010)
        self.assertEqual((yield self.dut.detected.nak), 1)

    @usb_domain_test_case
    def test_stall(self):
        yield from self.provide_packet(0b00011110)
        self.assertEqual((yield self.dut.detected.stall), 1)

    @usb_domain_test_case
    def test_nyet(self):
        yield from self.provide_packet(0b10010110)
        self.assertEqual((yield self.dut.detected.nyet), 1)

class USBDataPacketReceiverTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBDataPacketReceiver
    FRAGMENT_ARGUMENTS  = {'standalone': True}

    @usb_domain_test_case
    def test_data_receive(self):
        dut = self.dut
        stream = self.dut.stream


        #    0xC3,                                           # PID: Data
        #    0x00, 0x05, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, # DATA
        #    0xEB, 0xBC                                      # CRC

        # Before we send anything, our stream should be inactive.
        self.assertEqual((yield stream.valid), 0)

        # After sending our PID, we shouldn't see our stream be active.
        yield from self.start_packet()
        yield from self.provide_byte(0xc3)
        self.assertEqual((yield stream.valid), 0)

        # The stream shouldn't go valid for our first two data bytes, either.
        for b in [0x00, 0x05]:
            yield from self.provide_byte(b)
            self.assertEqual((yield stream.valid), 0)

        # Check that our active PID was successfully captured, and our current on
        # hasn't yet been updated.
        self.assertEqual((yield self.dut.active_pid), 3)
        self.assertEqual((yield self.dut.packet_id),  0)

        # The third byte should finally trigger our stream output...
        yield from self.provide_byte(0x08)
        self.assertEqual((yield stream.valid), 1)

        # ... and we should see the first byte on our stream.
        self.assertEqual((yield stream.next),       1)
        self.assertEqual((yield stream.payload), 0x00)

        # If we pause RxValid, we nothing should advance.
        yield self.utmi.rx_valid.eq(0)

        yield from self.provide_byte(0x08)
        self.assertEqual((yield stream.next),       0)
        self.assertEqual((yield stream.payload), 0x00)

        # Resuming should continue our advance...
        yield self.utmi.rx_valid.eq(1)

        # ... and we should process the remainder of the input
        for b in [0x00, 0x00, 0x00, 0x00, 0x00, 0xEB, 0xBC]:
            yield from self.provide_byte(b)

        # ... remaining two bytes behind.
        self.assertEqual((yield stream.next),       1)
        self.assertEqual((yield stream.payload), 0x00)


        # When we stop our packet, we should see our stream stop as well.
        # The last two bytes, our CRC, shouldn't be included.
        yield from self.end_packet()
        yield

        # And, since we sent a valid packet, we should see a pulse indicating the packet is valid.
        self.assertEqual((yield stream.valid),              0)
        self.assertEqual((yield self.dut.packet_complete),  1)

        # After an inter-packet delay, we should see that we're ready to respond.
        yield from self.advance_cycles(9)
        self.assertEqual((yield self.dut.ready_for_response), 0)


    @usb_domain_test_case
    def test_zlp(self):
        dut = self.dut
        stream = self.dut.stream

        #    0x4B        # DATA1
        #    0x00, 0x00  # CRC

        # Send our data PID.
        yield from self.start_packet()
        yield from self.provide_byte(0x4B)

        # Send our CRC.
        for b in [0x00, 0x00]:
            yield from self.provide_byte(b)
            self.assertEqual((yield stream.valid), 0)

        yield from self.end_packet()
        yield

        self.assertEqual((yield self.dut.packet_complete),  1)


class USBDataPacketDeserializerTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBDataPacketDeserializer

    def instantiate_dut(self):
        return super().instantiate_dut(extra_arguments={'create_crc_generator': True})


    @usb_domain_test_case
    def test_packet_rx(self):
        yield from self.provide_packet(
            0b11000011,                                     # PID
            0b00100011, 0b01000101, 0b01100111, 0b10001001, # DATA
            0b00001110, 0b00011100                          # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 1, "packet not recognized")
        self.assertEqual((yield self.dut.length),     4)
        self.assertEqual((yield self.dut.packet[0]),  0b00100011)
        self.assertEqual((yield self.dut.packet[1]),  0b01000101)
        self.assertEqual((yield self.dut.packet[2]),  0b01100111)
        self.assertEqual((yield self.dut.packet[3]),  0b10001001)


    @usb_domain_test_case
    def test_captured_usb_sample(self):
        yield from self.provide_packet(
            0xC3,                                           # PID: Data
            0x00, 0x05, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, # DATA
            0xEB, 0xBC                                      # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 1, "packet not recognized")

    @usb_domain_test_case
    def test_invalid_rx(self):
        yield from self.provide_packet(
            0b11000011,                                     # PID
            0b11111111, 0b11111111, 0b11111111, 0b11111111, # DATA
            0b00011100, 0b00001110                          # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 0, 'accepted invalid CRC!')

class USBDataPacketGeneratorTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY = 60e6

    FRAGMENT_UNDER_TEST = USBDataPacketGenerator
    FRAGMENT_ARGUMENTS  = {'standalone': True}

    def initialize_signals(self):
        # Model our PHY is always accepting data, by default.
        yield self.dut.tx.ready.eq(1)


    @usb_domain_test_case
    def test_simple_data_generation(self):
        dut    = self.dut
        stream = self.dut.stream
        tx     = self.dut.tx

        # We'll request that a simple USB packet be sent. We expect the following data:
        #    0xC3,                                           # PID: Data
        #    0x00, 0x05, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, # DATA
        #    0xEB, 0xBC                                      # CRC

        # Before we send anything, we shouldn't be transmitting.
        self.assertEqual((yield dut.tx.valid), 0)

        # Work with DATA0 packet IDs.
        yield dut.data_pid.eq(0)

        # Start sending our first byte.
        yield stream.first.eq(1)
        yield stream.valid.eq(1)
        yield stream.payload.eq(0x00)
        yield

        # Once our first byte has been provided, our transmission should
        # start (valid=1), and we should see our data PID.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data), 0xc3)

        # We shouldn't consume any data, yet, as we're still
        # transmitting our PID.
        self.assertEqual((yield stream.ready), 0)

        # Drop our first value back to zero, as it should also work as a strobe.
        yield stream.first.eq(0)

        # One cycle later, we should see our first data byte, and our
        # stream should indicate that data was consumed.
        yield
        self.assertEqual((yield tx.data), 0x00)
        self.assertEqual((yield stream.ready), 1)

        # Provide the remainder of our data, and make sure that our
        # output value mirrors it.
        for datum in [0x05, 0x08, 0x00, 0x00, 0x00, 0x00]:
            yield stream.payload.eq(datum)
            yield
            self.assertEqual((yield tx.data), datum)

        # Finally, provide our last data value.
        yield stream.payload.eq(0x00)
        yield stream.last.eq(1)
        yield

        # Drop our stream-valid to zero after the last stream byte.
        yield stream.valid.eq(0)

        # We should now see that we're no longer consuming data...
        yield
        self.assertEqual((yield stream.ready), 0)

        # ... but the transmission is still valid; and now presenting our CRC...
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0xeb)

        # ... which is two-bytes long.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0xbc)

        # Once our CRC is completed, our transmission should stop.
        yield
        self.assertEqual((yield tx.valid), 0)


    @usb_domain_test_case
    def test_single_byte(self):
        stream = self.dut.stream

        # Request single byte.
        yield stream.first.eq(1)
        yield stream.last.eq(1)
        yield stream.valid.eq(1)
        yield stream.payload.eq(0xAB)
        yield from self.wait_until(stream.ready)

        # Drop our last back to zero, immediately.
        yield stream.last.eq(0)
        yield stream.first.eq(0)
        yield stream.valid.eq(0)

        yield from self.advance_cycles(10)


    @usb_domain_test_case
    def test_zlp_generation(self):
        stream = self.dut.stream
        tx     = self.dut.tx

        # Request a ZLP.
        yield stream.first.eq(0)
        yield stream.last.eq(1)
        yield stream.valid.eq(1)
        yield

        # Drop our last back to zero, immediately.
        yield stream.last.eq(0)

        # Once our first byte has been provided, our transmission should
        # start (valid=1), and we should see our data PID.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data), 0xc3)

        # Drop our stream-valid to zero after the last stream byte.
        yield stream.valid.eq(0)

        # We should now see that we're no longer consuming data...
        yield
        self.assertEqual((yield stream.ready), 0)

        # ... but the transmission is still valid; and now presenting our CRC...
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0x0)

        # ... which is two-bytes long.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0x0)


class USBHandshakeGeneratorTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY = 60e6

    FRAGMENT_UNDER_TEST  = USBHandshakeGenerator


    @usb_domain_test_case
    def test_ack_generation(self):
        dut = self.dut

        # Before we request anything, our data shouldn't be valid.
        self.assertEqual((yield dut.tx.valid), 0)

        # When we request an ACK...
        yield dut.issue_ack.eq(1)
        yield
        yield dut.issue_ack.eq(0)

        # ... we should see an ACK packet on our data lines...
        yield
        self.assertEqual((yield dut.tx.data), USBHandshakeGenerator._PACKET_ACK)

        # ... our transmit request should be valid.
        self.assertEqual((yield dut.tx.valid), 1)

        # It should remain valid...
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.tx.valid), 1)

        # ... until the UTMI transceiver marks it as accepted...
        yield dut.tx.ready.eq(1)
        yield

        # ... when our packet should be marked as invalid.
        yield
        self.assertEqual((yield dut.tx.valid), 0)


    @usb_domain_test_case
    def test_already_ready(self):
        dut = self.dut

        # Start off with our transmitter ready to receive.
        yield dut.tx.ready.eq(1)

        # When we request an ACK...
        yield dut.issue_ack.eq(1)
        yield
        yield dut.issue_ack.eq(0)

        # ... we should see an ACK packet on our data lines...
        yield
        self.assertEqual((yield dut.tx.data), USBHandshakeGenerator._PACKET_ACK)

        # ... our transmit request should be valid...
        self.assertEqual((yield dut.tx.valid), 1)

        # ... and then drop out of being valid after one cycle.
        yield
        self.assertEqual((yield dut.tx.valid), 0)


class USBInterpacketTimerTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY = 60e6

    def instantiate_dut(self):
        dut = USBInterpacketTimer()

        # Create our primary timer interface.
        self.interface = InterpacketTimerInterface()
        dut.add_interface(self.interface)

        return dut


    def initialize_signals(self):
        # Assume FS for our tests, unless overridden.
        yield self.dut.speed(USBSpeed.FULL)


    def test_resets_and_delays(self):
        yield from self.advance_cycles(4)
        interface = self.interface

        # Trigger a cycle reset.
        yield interface.start.eq(1)
        yield
        yield interface.start.eq(0)

        # We should start off with no timer outputs high.
        self.assertEqual((yield interface.tx_allowed), 0)
        self.assertEqual((yield interface.tx_timeout), 0)
        self.assertEqual((yield interface.rx_timeout), 0)

        # 10 cycles later, we should see our first timer output.
        yield from self.advance_cycles(10)
        self.assertEqual((yield interface.tx_allowed), 1)
        self.assertEqual((yield interface.tx_timeout), 0)
        self.assertEqual((yield interface.rx_timeout), 0)

        # 22 cycles later (32 total), we should see our second timer output.
        yield from self.advance_cycles(22)
        self.assertEqual((yield interface.tx_allowed), 0)
        self.assertEqual((yield interface.tx_timeout), 1)
        self.assertEqual((yield interface.rx_timeout), 0)

        # 58 cycles later (80 total), we should see our third timer output.
        yield from self.advance_cycles(22)
        self.assertEqual((yield interface.tx_allowed), 0)
        self.assertEqual((yield interface.tx_timeout), 0)
        self.assertEqual((yield interface.rx_timeout), 1)

        # Ensure that the timers don't go high again.
        for _ in range(32):
            self.assertEqual((yield self.rx_to_tx_min),     0)
            self.assertEqual((yield self.rx_to_tx_max),     0)
            self.assertEqual((yield self.tx_to_rx_timeout), 0)
