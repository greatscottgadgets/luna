#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test       import LunaUSBGatewareTestCase, usb_domain_test_case

from luna.gateware.usb.stream import USBOutStreamBoundaryDetector

class USBOutStreamBoundaryDetectorTest(LunaUSBGatewareTestCase):
    FRAGMENT_UNDER_TEST   = USBOutStreamBoundaryDetector

    @usb_domain_test_case
    def test_boundary_detection(self):
        dut                 = self.dut
        processed_stream    = self.dut.processed_stream
        unprocesesed_stream = self.dut.unprocessed_stream

        # Before we see any data, we should have all of our strobes de-asserted, and an invalid stream.
        self.assertEqual((yield processed_stream.valid), 0)
        self.assertEqual((yield processed_stream.next), 0)
        self.assertEqual((yield dut.first), 0)
        self.assertEqual((yield dut.last), 0)

        # If our stream goes valid...
        yield unprocesesed_stream.valid.eq(1)
        yield unprocesesed_stream.next.eq(1)
        yield unprocesesed_stream.payload.eq(0xAA)
        yield

        # ... we shouldn't see anything this first cycle...
        self.assertEqual((yield processed_stream.valid), 0)
        self.assertEqual((yield processed_stream.next), 0)
        self.assertEqual((yield dut.first), 0)
        self.assertEqual((yield dut.last), 0)

        # ... but after two cycles...
        yield unprocesesed_stream.payload.eq(0xBB)
        yield
        yield unprocesesed_stream.payload.eq(0xCC)
        yield

        # ... we should see a valid stream's first byte.
        self.assertEqual((yield processed_stream.valid), 1)
        self.assertEqual((yield processed_stream.next),  1)
        self.assertEqual((yield processed_stream.payload),  0xAA)
        self.assertEqual((yield dut.first), 1)
        self.assertEqual((yield dut.last), 0)
        yield unprocesesed_stream.payload.eq(0xDD)

        # ... followed by a byte that's neither first nor last...
        yield
        self.assertEqual((yield processed_stream.payload),  0xBB)
        self.assertEqual((yield dut.first), 0)
        self.assertEqual((yield dut.last), 0)

        # Once our stream is no longer valid...
        yield unprocesesed_stream.valid.eq(0)
        yield unprocesesed_stream.next.eq(0)
        yield
        yield

        # ... we should see our final byte.
        self.assertEqual((yield processed_stream.payload),  0xDD)
        self.assertEqual((yield dut.first), 0)
        self.assertEqual((yield dut.last), 1)

