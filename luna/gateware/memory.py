#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

"""
This module contains definitions of memory units that work well for USB applications.
"""

import unittest

from amaranth import Elaboratable, Module, Signal, Memory
from amaranth.hdl.xfrm import DomainRenamer


from .test import LunaGatewareTestCase, sync_test_case


class TransactionalizedFIFO(Elaboratable):
    """ Transactionalized, buffer first-in-first-out queue.

    This FIFO is "transactionalized", which means that it allows sets of reads and writes to be "undone".
    Effectively, this FIFO allows "rewinding" its read and write pointers to a previous point in time,
    which makes it ideal for USB transmission or receipt; where the protocol can require blocks of data
    to be retransmitted or ignored.

    Attributes
    ----------
    read_data: Signal(width), output
        Contains the next byte in the FIFO. Valid only when :attr:``empty`` is false.
    read_en: Signal(), input
        When asserted, the current :attr:``read_data`` will move to the next value. The data is not
        internally consumed/dequeued until :attr:``read_commit`` is asserted. This read can be "undone"
        by asserting :attr:``read_discard``. Should only be asserted when :attr:``empty`` is false.
    read_commit: Signal(), input
        Strobe; when asserted, any reads performed since the last commit will be "finalized".
        This effectively frees the memory associated with past reads. If this value is tied to '1',
        the read port on this FIFO gracefully degrades to non-transactionalized port.
    read_discard: Signal(), input
        Strobe; when asserted; any reads since the last commit will be "undone", placing the read pointer
        back at the queue position it had after the last :attr:``read_commit`.
    empty: Signal(), output
        Asserted when no data is available in the FIFO. This signal refers to whether data is available to
        read. :attr:``read_commit`` will not change this value; but :attr:``read_discard`` will.


    write_data: Signal(width), input
        Holds the byte to be added to the FIFO when :attr:``write_en`` is asserted.
    write_en: Signal(), input
        When asserted, the current :attr:``write_data`` will be added to the FIFO; but will not be ready for read
        until :attr:``write_commit`` is asserted. This write can be "undone" by asserting :attr:``write_discard``.
        Should only be asserted when :attr:``full`` is false.
    write_commit: Signal(), input
        Strobe; when asserted, any writes reads performed since the last commit will be "finalized".
        This makes the relevant data available for read.
    write_discard: Signal(), input
        Strobe; when asserted; any writes since the last commit will be "undone", placing the write pointer
        back at the queue position it had after the last :attr:``write_commit`. This frees the relevant memory
        for new writes.
    full: Signal(), output
        Asserted when no space is available for writes in the FIFO. :attr:``write_commit`` will not change
        this value; but :attr:``write_discard`` will.

    space_available: Signal(range(0, depth + 1)), output
        Indicates the amount of space available in the FIFO. Useful for knowing whether we can add e.g. an
        entire packet to the FIFO.


    Attributes
    ----------
    width: int
        The width of each entry in the FIFO.
    depth: int
        The number of allowed entries in the FIFO.
    name: str
        The name of the relevant FIFO; to produce nicer debug output.
        If not provided, Amaranth will attempt auto-detection.
    domain: str
        The name of the domain this module should exist in.
    """

    def __init__(self, *, width, depth, name=None, domain="sync"):
        self.width  = width
        self.depth  = depth
        self.name   = name
        self.domain = domain

        #
        # I/O port
        #
        self.read_data        = Signal(width)
        self.read_en          = Signal()
        self.read_commit      = Signal()
        self.read_discard     = Signal()
        self.empty            = Signal()

        self.write_data       = Signal(width)
        self.write_en         = Signal()
        self.write_commit     = Signal()
        self.write_discard    = Signal()
        self.full             = Signal()

        self.space_available  = Signal(range(0, depth + 1))


    def elaborate(self, platform):
        m = Module()

        # Range shortcuts for internal signals.
        address_range = range(0, self.depth + 1)

        #
        # Core internal "backing store".
        #
        memory = Memory(width=self.width, depth=self.depth + 1, name=self.name)
        m.submodules.read_port  = read_port  = memory.read_port()
        m.submodules.write_port = write_port = memory.write_port()

        # Always connect up our memory's data/en ports to ours.
        m.d.comb += [
            self.read_data  .eq(read_port.data),

            write_port.data .eq(self.write_data),
            write_port.en   .eq(self.write_en & ~self.full)
        ]

        #
        # Write port.
        #

        # We'll track two pieces of data: our _committed_ write position, and our current un-committed write one.
        # This will allow us to rapidly backtrack to our pre-commit position.
        committed_write_pointer = Signal(address_range)
        current_write_pointer   = Signal(address_range)
        m.d.comb += write_port.addr.eq(current_write_pointer)


        # Compute the location for the next write, accounting for wraparound. We'll not assume a binary-sized
        # buffer; so we'll compute the wraparound manually.
        next_write_pointer      = Signal.like(current_write_pointer)
        with m.If(current_write_pointer == self.depth):
            m.d.comb += next_write_pointer.eq(0)
        with m.Else():
            m.d.comb += next_write_pointer.eq(current_write_pointer + 1)


        # If we're writing to the fifo, update our current write position.
        with m.If(self.write_en & ~self.full):
            m.d.sync += current_write_pointer.eq(next_write_pointer)

        # If we're committing a FIFO write, update our committed position.
        with m.If(self.write_commit):
            m.d.sync += committed_write_pointer.eq(current_write_pointer)

        # If we're discarding our current write, reset our current position,
        with m.If(self.write_discard):
            m.d.sync += current_write_pointer.eq(committed_write_pointer)


        #
        # Read port.
        #

        # We'll track two pieces of data: our _committed_ read position, and our current un-committed read one.
        # This will allow us to rapidly backtrack to our pre-commit position.
        committed_read_pointer = Signal(address_range)
        current_read_pointer   = Signal(address_range)


        # Compute the location for the next read, accounting for wraparound. We'll not assume a binary-sized
        # buffer; so we'll compute the wraparound manually.
        next_read_pointer      = Signal.like(current_read_pointer)
        with m.If(current_read_pointer == self.depth):
            m.d.comb += next_read_pointer.eq(0)
        with m.Else():
            m.d.comb += next_read_pointer.eq(current_read_pointer + 1)


        # Our memory always takes a single cycle to provide its read output; so we'll update its address
        # "one cycle in advance". Accordingly, if we're about to advance the FIFO, we'll use the next read
        # address as our input. If we're not, we'll use the current one.
        with m.If(self.read_en & ~self.empty):
            m.d.comb += read_port.addr.eq(next_read_pointer)
        with m.Else():
            m.d.comb += read_port.addr.eq(current_read_pointer)


        # If we're reading from our the fifo, update our current read position.
        with m.If(self.read_en & ~self.empty):
            m.d.sync += current_read_pointer.eq(next_read_pointer)

        # If we're committing a FIFO write, update our committed position.
        with m.If(self.read_commit):
            m.d.sync += committed_read_pointer.eq(current_read_pointer)

        # If we're discarding our current write, reset our current position,
        with m.If(self.read_discard):
            m.d.sync += current_read_pointer.eq(committed_read_pointer)


        #
        # FIFO status.
        #

        # Our FIFO is empty if our read and write pointers are in the same. We'll use the current
        # read position (which leads ahead) and the committed write position (which lags behind).
        m.d.comb += self.empty.eq(current_read_pointer == committed_write_pointer)

        # For our space available, we'll use the current write position (which leads ahead) and our committed
        # read position (which lags behind). This yields two cases: one where the buffer isn't wrapped around,
        # and one where it is.
        with m.If(self.full):
            m.d.comb += self.space_available.eq(0)
        with m.Elif(committed_read_pointer <= current_write_pointer):
            m.d.comb += self.space_available.eq(self.depth - (current_write_pointer - committed_read_pointer))
        with m.Else():
            m.d.comb += self.space_available.eq(committed_read_pointer - current_write_pointer - 1)

        # Our FIFO is full if we don't have any space available.
        m.d.comb += self.full.eq(next_write_pointer == committed_read_pointer)


        # If we're not supposed to be in the sync domain, rename our sync domain to the target.
        if self.domain != "sync":
            m = DomainRenamer({"sync": self.domain})(m)

        return m



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


if __name__ == "__main__":
    unittest.main()
