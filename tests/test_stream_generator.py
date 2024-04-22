#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test       import LunaUSBGatewareTestCase, LunaSSGatewareTestCase, ss_domain_test_case, usb_domain_test_case

from luna.gateware.stream.generator import ConstantStreamGenerator
from luna.gateware.usb.stream import SuperSpeedStreamInterface

class ConstantStreamGeneratorTest(LunaUSBGatewareTestCase):
    FRAGMENT_UNDER_TEST = ConstantStreamGenerator
    FRAGMENT_ARGUMENTS  = {'constant_data': b"HELLO, WORLD", 'domain': "usb", 'max_length_width': 16}

    @usb_domain_test_case
    def test_basic_transmission(self):
        dut = self.dut

        # Establish a very high max length; so it doesn't apply.
        yield dut.max_length.eq(1000)

        # We shouldn't see a transmission before we request a start.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid), 0)
        self.assertEqual((yield dut.stream.first), 0)
        self.assertEqual((yield dut.stream.last),  0)

        # Once we pulse start, we should see the transmission start,
        # and we should see our first byte of data.
        yield from self.pulse(dut.start)
        self.assertEqual((yield dut.stream.valid),   1)
        self.assertEqual((yield dut.stream.payload), ord('H'))
        self.assertEqual((yield dut.stream.first),   1)

        # That data should remain there until we accept it.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid),   1)
        self.assertEqual((yield dut.stream.payload), ord('H'))

        # Once we indicate that we're accepting data...
        yield dut.stream.ready.eq(1)
        yield

        # ... we should start seeing the remainder of our transmission.
        for i in 'ELLO':
            yield
            self.assertEqual((yield dut.stream.payload), ord(i))
            self.assertEqual((yield dut.stream.first),   0)


        # If we drop the 'accepted', we should still see the next byte...
        yield dut.stream.ready.eq(0)
        yield
        self.assertEqual((yield dut.stream.payload), ord(','))

        # ... but that byte shouldn't be accepted, so we should remain there.
        yield
        self.assertEqual((yield dut.stream.payload), ord(','))

        # If we start accepting data again...
        yield dut.stream.ready.eq(1)
        yield

        # ... we should see the remainder of the stream.
        for i in ' WORLD':
            yield
            self.assertEqual((yield dut.stream.payload), ord(i))


        # On the last byte of data, we should see last = 1.
        self.assertEqual((yield dut.stream.last),   1)

        # After the last datum, we should see valid drop to '0'.
        yield
        self.assertEqual((yield dut.stream.valid), 0)

    @usb_domain_test_case
    def test_basic_start_position(self):
        dut = self.dut

        # Start at position 2
        yield dut.start_position.eq(2)

        # Establish a very high max length; so it doesn't apply.
        yield dut.max_length.eq(1000)

        # We shouldn't see a transmission before we request a start.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid), 0)
        self.assertEqual((yield dut.stream.first), 0)
        self.assertEqual((yield dut.stream.last),  0)

        # Once we pulse start, we should see the transmission start,
        # and we should see our first byte of data.
        yield from self.pulse(dut.start)
        self.assertEqual((yield dut.stream.valid),   1)
        self.assertEqual((yield dut.stream.payload), ord('L'))
        self.assertEqual((yield dut.stream.first),   1)

        # That data should remain there until we accept it.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid),   1)
        self.assertEqual((yield dut.stream.payload), ord('L'))

        # Once we indicate that we're accepting data...
        yield dut.stream.ready.eq(1)
        yield

        # ... we should start seeing the remainder of our transmission.
        for i in 'LO':
            yield
            self.assertEqual((yield dut.stream.payload), ord(i))
            self.assertEqual((yield dut.stream.first),   0)


        # If we drop the 'accepted', we should still see the next byte...
        yield dut.stream.ready.eq(0)
        yield
        self.assertEqual((yield dut.stream.payload), ord(','))

        # ... but that byte shouldn't be accepted, so we should remain there.
        yield
        self.assertEqual((yield dut.stream.payload), ord(','))

        # If we start accepting data again...
        yield dut.stream.ready.eq(1)
        yield

        # ... we should see the remainder of the stream.
        for i in ' WORLD':
            yield
            self.assertEqual((yield dut.stream.payload), ord(i))


        # On the last byte of data, we should see last = 1.
        self.assertEqual((yield dut.stream.last),   1)

        # After the last datum, we should see valid drop to '0'.
        yield
        self.assertEqual((yield dut.stream.valid), 0)

    @usb_domain_test_case
    def test_max_length(self):
        dut = self.dut

        yield dut.stream.ready.eq(1)
        yield dut.max_length.eq(6)

        # Once we pulse start, we should see the transmission start,
        yield from self.pulse(dut.start)

        # ... we should start seeing the remainder of our transmission.
        for i in 'HELLO':
            self.assertEqual((yield dut.stream.payload), ord(i))
            yield


        # On the last byte of data, we should see last = 1.
        self.assertEqual((yield dut.stream.last),   1)

        # After the last datum, we should see valid drop to '0'.
        yield
        self.assertEqual((yield dut.stream.valid), 0)



class ConstantStreamGeneratorWideTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = ConstantStreamGenerator
    FRAGMENT_ARGUMENTS  = dict(
        domain           = "ss",
        constant_data    = b"HELLO WORLD",
        stream_type      = SuperSpeedStreamInterface,
        max_length_width = 16
    )


    @ss_domain_test_case
    def test_basic_transmission(self):
        dut = self.dut

        # Establish a very high max length; so it doesn't apply.
        yield dut.max_length.eq(1000)

        # We shouldn't see a transmission before we request a start.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid), 0)
        self.assertEqual((yield dut.stream.first), 0)
        self.assertEqual((yield dut.stream.last),  0)

        # Once we pulse start, we should see the transmission start,
        # and we should see our first byte of data.
        yield from self.pulse(dut.start)
        self.assertEqual((yield dut.stream.valid),   0b1111)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"HELL", byteorder="little"))
        self.assertEqual((yield dut.stream.first),   1)

        # That data should remain there until we accept it.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid),   0b1111)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"HELL", byteorder="little"))

        # Once we indicate that we're accepting data...
        yield dut.stream.ready.eq(1)
        yield

        # ... we should start seeing the remainder of our transmission.
        yield
        self.assertEqual((yield dut.stream.valid),   0b1111)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"O WO", byteorder="little"))
        self.assertEqual((yield dut.stream.first),   0)


        yield
        self.assertEqual((yield dut.stream.valid),   0b111)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"RLD", byteorder="little"))
        self.assertEqual((yield dut.stream.first),   0)


        # On the last byte of data, we should see last = 1.
        self.assertEqual((yield dut.stream.last),   1)

        # After the last datum, we should see valid drop to '0'.
        yield
        self.assertEqual((yield dut.stream.valid), 0)


    @ss_domain_test_case
    def test_max_length_transmission(self):
        dut = self.dut

        # Apply a maximum length of six bytes.
        yield dut.max_length.eq(6)
        yield dut.stream.ready.eq(1)

        # Once we pulse start, we should see the transmission start,
        # and we should see our first byte of data.
        yield from self.pulse(dut.start)
        self.assertEqual((yield dut.stream.valid),   0b1111)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"HELL", byteorder="little"))
        self.assertEqual((yield dut.stream.first),   1)

        # We should then see only two bytes of our remainder.
        yield
        self.assertEqual((yield dut.stream.valid),   0b0011)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"O WO", byteorder="little"))
        self.assertEqual((yield dut.stream.first),   0)
        self.assertEqual((yield dut.stream.last),    1)


    @ss_domain_test_case
    def test_very_short_max_length(self):
        dut = self.dut

        # Apply a maximum length of six bytes.
        yield dut.max_length.eq(2)

        # Once we pulse start, we should see the transmission start,
        # and we should see our first word of data.
        yield from self.pulse(dut.start)
        self.assertEqual((yield dut.stream.valid),   0b0011)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"HELL", byteorder="little"))
        self.assertEqual((yield dut.stream.first),   1)
        self.assertEqual((yield dut.stream.last),    1)

        # Our data should remain there until it's accepted.
        yield dut.stream.ready.eq(1)
        yield
        self.assertEqual((yield dut.stream.valid),   0b0011)
        self.assertEqual((yield dut.stream.payload), int.from_bytes(b"HELL", byteorder="little"))
        self.assertEqual((yield dut.stream.first),   1)
        self.assertEqual((yield dut.stream.last),    1)

        # After acceptance, valid should drop back to false.
        yield
        self.assertEqual((yield dut.stream.valid),   0b0000)

