#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test import LunaGatewareTestCase, sync_test_case

from luna.gateware.memory import TransactionalizedFIFO

class TransactionalizedFIFOTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = TransactionalizedFIFO
    FRAGMENT_ARGUMENTS = {'width': 8, 'depth': 16}

    def initialize_signals(self):
        yield self.dut.write_en.eq(0)

    @sync_test_case
    def test_simple_fill(self):
        dut = self.dut

        # Our FIFO should start off empty; and with a full depth of free space.
        self.assertEqual((yield dut.empty),           1)
        self.assertEqual((yield dut.full),            0)
        self.assertEqual((yield dut.space_available), 16)

        # If we add a byte to the queue...
        yield dut.write_data.eq(0xAA)
        yield from self.pulse(dut.write_en)

        # ... we should have less space available ...
        self.assertEqual((yield dut.space_available), 15)

        # ... but we still should be "empty", as we won't have data to read until we commit.
        self.assertEqual((yield dut.empty), 1)

        # Once we _commit_ our write, we should suddenly have data to read.
        yield from self.pulse(dut.write_commit)
        self.assertEqual((yield dut.empty), 0)

        # If we read a byte, we should see the FIFO become empty...
        yield from self.pulse(dut.read_en)
        self.assertEqual((yield dut.empty), 1)

        # ... but we shouldn't see more space become available until we commit the read.
        self.assertEqual((yield dut.space_available), 15)
        yield from self.pulse(dut.read_commit)
        self.assertEqual((yield dut.space_available), 16)

        # If we write 16 more bytes of data...
        yield dut.write_en.eq(1)
        for i in range(16):
            yield dut.write_data.eq(i)
            yield
        yield dut.write_en.eq(0)

        # ... our buffer should be full, but also empty.
        # This paradox exists as we've filled our buffer with uncomitted data.
        yield
        self.assertEqual((yield dut.full),  1)
        self.assertEqual((yield dut.empty), 1)

        # Once we _commit_ our data, it should suddenly stop being empty.
        yield from self.pulse(dut.write_commit)
        self.assertEqual((yield dut.empty), 0)

        # Reading a byte _without committing_ shouldn't change anything about empty/full/space-available...
        yield from self.pulse(dut.read_en)
        self.assertEqual((yield dut.empty), 0)
        self.assertEqual((yield dut.full),  1)
        self.assertEqual((yield dut.space_available),  0)

        # ... but committing should increase our space available by one, and make our buffer no longer full.
        yield from self.pulse(dut.read_commit)
        self.assertEqual((yield dut.empty), 0)
        self.assertEqual((yield dut.full),  0)
        self.assertEqual((yield dut.space_available),  1)

        # Reading/committing another byte should increment our space available.
        yield from self.pulse(dut.read_en)
        yield from self.pulse(dut.read_commit)
        self.assertEqual((yield dut.space_available),  2)

        # Writing data into the buffer should then fill it back up again...
        yield dut.write_en.eq(1)
        for i in range(2):
            yield dut.write_data.eq(i)
            yield
        yield dut.write_en.eq(0)

        # ... meaning it will again be full, and have no space remaining.
        yield
        self.assertEqual((yield dut.full),             1)
        self.assertEqual((yield dut.space_available),  0)

        # If we _discard_ this data, we should go back to having two bytes available.
        yield from self.pulse(dut.write_discard)
        self.assertEqual((yield dut.full),             0)
        self.assertEqual((yield dut.space_available),  2)

        # If we read the data that's remaining in the fifo...
        yield dut.read_en.eq(1)
        for i in range(2, 16):
            yield
            self.assertEqual((yield dut.read_data), i)
        yield dut.read_en.eq(0)

        # ... our buffer should again be empty.
        yield
        self.assertEqual((yield dut.empty),            1)
        self.assertEqual((yield dut.space_available),  2)

        # If we _discard_ our current read, we should then see our buffer no longer empty...
        yield from self.pulse(dut.read_discard)
        self.assertEqual((yield dut.empty),            0)

        # and we should be able to read the same data again.
        yield dut.read_en.eq(1)
        for i in range(2, 16):
            yield
            self.assertEqual((yield dut.read_data), i)
        yield dut.read_en.eq(0)

        # On committing this, we should see a buffer that is no longer full, and is really empty.
        yield from self.pulse(dut.read_commit)
        self.assertEqual((yield dut.empty),            1)
        self.assertEqual((yield dut.full),             0)
        self.assertEqual((yield dut.space_available),  16)
