#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test.utils import LunaGatewareTestCase, sync_test_case

from luna.gateware.interface.uart import UARTMultibyteTransmitter, UARTTransmitter

class UARTTransmitterTest(LunaGatewareTestCase):
    DIVISOR = 10

    FRAGMENT_UNDER_TEST = UARTTransmitter
    FRAGMENT_ARGUMENTS = dict(divisor=DIVISOR)


    def advance_half_bit(self):
        yield from self.advance_cycles(self.DIVISOR // 2)

    def advance_bit(self):
        yield from self.advance_cycles(self.DIVISOR)


    def assert_data_sent(self, byte_expected):
        dut = self.dut

        # Our start bit should remain present until the next bit period.
        yield from self.advance_half_bit()
        self.assertEqual((yield dut.tx), 0)

        # We should then see each bit of our data, LSB first.
        bits = [int(i) for i in f"{byte_expected:08b}"]
        for bit in bits[::-1]:
            yield from self.advance_bit()
            self.assertEqual((yield dut.tx), bit)

        # Finally, we should see a stop bit.
        yield from self.advance_bit()
        self.assertEqual((yield dut.tx), 1)


    @sync_test_case
    def test_burst_transmit(self):
        dut = self.dut
        stream = dut.stream

        # We should remain idle until a transmit is requested...
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.idle), 1)
        self.assertEqual((yield dut.stream.ready), 1)

        # ... and our tx line should idle high.
        self.assertEqual((yield dut.tx), 1)

        # First, transmit 0x55 (maximum transition rate).
        yield stream.payload.eq(0x55)
        yield stream.valid.eq(1)

        # We should see our data become accepted; and we
        # should see a start bit.
        yield
        self.assertEqual((yield stream.ready), 1)
        yield
        self.assertEqual((yield dut.tx), 0)

        # Provide our next byte of data once the current
        # one has been accepted. Changing this before the tests
        # below ensures that we validate that data is latched properly.
        yield stream.payload.eq(0x66)

        # Ensure we get our data correctly.
        yield from self.assert_data_sent(0x55)
        yield from self.assert_data_sent(0x66)

        # Stop transmitting after the next frame.
        yield stream.valid.eq(0)

        # Ensure we actually stop.
        yield from self.advance_bit()
        self.assertEqual((yield dut.idle), 1)


class UARTMultibyteTransmitterTest(LunaGatewareTestCase):
    DIVISOR = 10

    FRAGMENT_UNDER_TEST = UARTMultibyteTransmitter
    FRAGMENT_ARGUMENTS = dict(divisor=DIVISOR, byte_width=4)


    def advance_half_bit(self):
        yield from self.advance_cycles(self.DIVISOR // 2)

    def advance_bit(self):
        yield from self.advance_cycles(self.DIVISOR)


    def assert_data_sent(self, byte_expected):
        dut = self.dut

        # Our start bit should remain present until the next bit period.
        yield from self.advance_half_bit()
        self.assertEqual((yield dut.tx), 0)

        # We should then see each bit of our data, LSB first.
        bits = [int(i) for i in f"{byte_expected:08b}"]
        for bit in bits[::-1]:
            yield from self.advance_bit()
            self.assertEqual((yield dut.tx), bit)

        # Finally, we should see a stop bit.
        yield from self.advance_bit()
        self.assertEqual((yield dut.tx), 1)

        yield from self.advance_cycles(2)


    @sync_test_case
    def test_burst_transmit(self):
        dut = self.dut
        stream = dut.stream

        # We should remain idle until a transmit is requested...
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.idle), 1)
        self.assertEqual((yield dut.stream.ready), 1)

        # Transmit a four-byte word.
        yield stream.payload.eq(0x11223355)
        yield stream.valid.eq(1)

        # We should see our data become accepted; and we
        # should see a start bit.
        yield
        self.assertEqual((yield stream.ready), 1)

        # Ensure we get our data correctly, and that our transmitter
        # isn't accepting data mid-frame.
        yield from self.assert_data_sent(0x55)
        self.assertEqual((yield stream.ready), 0)
        yield from self.assert_data_sent(0x33)
