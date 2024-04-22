#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test import usb_domain_test_case
from .test_usb2_packet  import USBPacketizerTest

from luna.gateware.usb.usb2         import USBSpeed
from luna.gateware.usb.usb2.request import USBSetupDecoder

class USBSetupDecoderTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBSetupDecoder
    FRAGMENT_ARGUMENTS = {'standalone': True}


    def initialize_signals(self):

        # Assume high speed.
        yield self.dut.speed.eq(USBSpeed.HIGH)


    def provide_reference_setup_transaction(self):
        """ Provide a reference SETUP transaction. """

        # Provide our setup packet.
        yield from self.provide_packet(
            0b00101101, # PID: SETUP token.
            0b00000000, 0b00010000 # Address 0, endpoint 0, CRC
        )

        # Provide our data packet.
        yield from self.provide_packet(
            0b11000011,   # PID: DATA0
            0b0_10_00010, # out vendor request to endpoint
            12,           # request number 12
            0xcd, 0xab,   # value  0xABCD (little endian)
            0x23, 0x01,   # index  0x0123
            0x78, 0x56,   # length 0x5678
            0x3b, 0xa2,   # CRC
        )


    @usb_domain_test_case
    def test_valid_sequence_receive(self):
        dut = self.dut

        # Before we receive anything, we shouldn't have a new packet.
        self.assertEqual((yield dut.packet.received), 0)

        # Simulate the host sending basic setup data.
        yield from self.provide_reference_setup_transaction()

        # We're high speed, so we should be ACK'ing immediately.
        self.assertEqual((yield dut.ack), 1)

        # We now should have received a new setup request.
        yield
        self.assertEqual((yield dut.packet.received), 1)

        # Validate that its values are as we expect.
        self.assertEqual((yield dut.packet.is_in_request), 0       )
        self.assertEqual((yield dut.packet.type),          0b10    )
        self.assertEqual((yield dut.packet.recipient),     0b00010 )
        self.assertEqual((yield dut.packet.request),       12      )
        self.assertEqual((yield dut.packet.value),         0xabcd  )
        self.assertEqual((yield dut.packet.index),         0x0123  )
        self.assertEqual((yield dut.packet.length),        0x5678  )


    @usb_domain_test_case
    def test_fs_interpacket_delay(self):
        dut = self.dut

        # Place our DUT into full speed mode.
        yield dut.speed.eq(USBSpeed.FULL)

        # Before we receive anything, we shouldn't have a new packet.
        self.assertEqual((yield dut.packet.received), 0)

        # Simulate the host sending basic setup data.
        yield from self.provide_reference_setup_transaction()

        # We shouldn't ACK immediately; we'll need to wait our interpacket delay.
        yield
        self.assertEqual((yield dut.ack), 0)

        # After our minimum interpacket delay, we should see an ACK.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.ack), 1)



    @usb_domain_test_case
    def test_short_setup_packet(self):
        dut = self.dut

        # Before we receive anything, we shouldn't have a new packet.
        self.assertEqual((yield dut.packet.received), 0)

        # Provide our setup packet.
        yield from self.provide_packet(
            0b00101101, # PID: SETUP token.
            0b00000000, 0b00010000 # Address 0, endpoint 0, CRC
        )

        # Provide our data packet; but shorter than expected.
        yield from self.provide_packet(
            0b11000011,                                     # PID: DATA0
            0b00100011, 0b01000101, 0b01100111, 0b10001001, # DATA
            0b00011100, 0b00001110                          # CRC
        )

        # This shouldn't count as a valid setup packet.
        yield
        self.assertEqual((yield dut.packet.received), 0)

