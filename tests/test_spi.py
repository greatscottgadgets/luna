#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test.utils import LunaGatewareTestCase, sync_test_case

from amaranth import Signal
from luna.gateware.interface.spi import SPIDeviceInterface, SPIRegisterInterface, SPIGatewareTestCase

class SPIDeviceInterfaceTest(SPIGatewareTestCase):
    FRAGMENT_UNDER_TEST = SPIDeviceInterface
    FRAGMENT_ARGUMENTS = dict(word_size=16, clock_polarity=1)

    def initialize_signals(self):
        yield self.dut.spi.cs.eq(0)


    @sync_test_case
    def test_spi_interface(self):

        # Ensure that we don't complete a word while CS is deasserted.
        for _ in range(10):
            self.assertEqual((yield self.dut.word_complete), 0)
            yield

        # Set the word we're expected to send, and then assert CS.
        yield self.dut.word_out.eq(0xABCD)
        yield

        yield self.dut.spi.cs.eq(1)
        yield

        # Verify that the SPI in/out behavior is what we expect.
        response = yield from self.spi_exchange_data(b"\xCA\xFE")
        self.assertEqual(response, b"\xAB\xCD")
        self.assertEqual((yield self.dut.word_in), 0xCAFE)


    @sync_test_case
    def test_spi_transmit_second_word(self):

        # Set the word we're expected to send, and then assert CS.
        yield self.dut.word_out.eq(0x0f00)
        yield

        yield self.dut.spi.cs.eq(1)
        yield

        # Verify that the SPI in/out behavior is what we expect.
        response = yield from self.spi_exchange_data(b"\x00\x00")
        self.assertEqual(response, b"\x0F\x00")



class SPIRegisterInterfaceTest(SPIGatewareTestCase):
    """ Tests for the SPI command interface. """

    def instantiate_dut(self):

        self.write_strobe = Signal()

        # Create a register and sample dataset to work with.
        dut = SPIRegisterInterface(default_read_value=0xDEADBEEF)
        dut.add_register(2, write_strobe=self.write_strobe)

        return dut


    def initialize_signals(self):
        # Start off with our clock low and the transaction idle.
        yield self.dut.spi.sck.eq(0)
        yield self.dut.spi.cs.eq(0)


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


    @sync_test_case
    def test_aborted_write_behavior(self):

        # Set an initial value...
        data = yield from self.spi_exchange_data(b"\x80\x02\x12\x34\x56\x78")

        # ... and then perform an incomplete write.
        data = yield from self.spi_exchange_data(b"\x80\x02\xAA\xBB")

        # We should return to being idle after CS is de-asserted...
        yield
        self.assertEqual((yield self.dut.idle), 1)

        # ... and our register data should not have changed.
        data = yield from self.spi_exchange_data(b"\x00\x02\x12\x34\x56\x78")
        self.assertEqual(bytes(data), b"\x00\x00\x12\x34\x56\x78")
