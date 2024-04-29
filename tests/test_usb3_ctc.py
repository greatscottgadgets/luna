#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test import LunaSSGatewareTestCase, ss_domain_test_case

from luna.gateware.usb.usb3.physical.ctc import CTCSkipRemover

class CTCSkipRemoverTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = CTCSkipRemover

    def initialize_signals(self):
        # Set up our streams to always ferry data in and out, where possible.
        yield self.dut.sink.valid.eq(1)
        yield self.dut.source.ready.eq(1)


    def provide_input(self, data, ctrl):
        yield self.dut.sink.data.eq(data)
        yield self.dut.sink.ctrl.eq(ctrl)
        yield


    @ss_domain_test_case
    def test_dual_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x71BA3C3C, 0b0011)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x11223344, 0b1100)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield
        self.assertEqual((yield source.data), 0x334471BA)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x33441122)
        self.assertEqual((yield source.ctrl), 0b11)


    @ss_domain_test_case
    def test_shifted_dual_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x713C3CBA, 0b0110)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x113C3C44, 0b0110)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield from self.provide_input(0x55667788, 0b0000)
        self.assertEqual((yield source.data), 0x114471BA)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x55667788)
        self.assertEqual((yield source.ctrl), 0)


    @ss_domain_test_case
    def test_single_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x3C556677, 0b1000)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x11223344, 0b1100)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield
        self.assertEqual((yield source.data), 0x44556677)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x44112233)
        self.assertEqual((yield source.ctrl), 0b110)


    @ss_domain_test_case
    def test_cycle_spread_skip_removal(self):
        source = self.dut.source

        # When we add data into the buffer...
        yield from self.provide_input(0xAABBCCDD, 0b0000)

        # ... we should see our line go valid only after four bytes are collected.
        self.assertEqual((yield source.valid), 0)
        yield from self.provide_input(0x3C556677, 0b1000)

        # Once it does go high, it should be accompanied by valid input data.
        self.assertEqual((yield source.valid), 1)
        self.assertEqual((yield source.data), 0xAABBCCDD)
        self.assertEqual((yield source.ctrl), 0)
        yield from self.provide_input(0x1122333C, 0b0001)

        # If data with SKPs were provided, our output should be invalid, until we
        # receive enough bytes to have four non-skip bytes.
        self.assertEqual((yield source.valid), 0)

        # Once we do, we should see a copy of our data without the SKPs included.
        yield from self.provide_input(0x44556677, 0b0000)
        self.assertEqual((yield source.data), 0x33556677)
        self.assertEqual((yield source.ctrl), 0)
        yield
        self.assertEqual((yield source.data), 0x66771122)
        self.assertEqual((yield source.ctrl), 0b0)

