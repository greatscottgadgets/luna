#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Utilities for building USB descriptors into gateware. """

import unittest
import functools
import operator
import struct

from nmigen                                  import *
from usb_protocol.emitters.descriptors       import DeviceDescriptorCollection
from usb_protocol.types.descriptors.standard import StandardDescriptorNumbers

from ..stream                          import USBInStreamInterface
from ...stream.generator               import ConstantStreamGenerator
from ...test                           import LunaUSBGatewareTestCase, usb_domain_test_case


class GetDescriptorHandlerSingleMemory(Elaboratable):
    """ Gateware that handles responding to GetDescriptor requests.

    Currently does not support descriptors in multiple languages.

    I/O port:
        I: value[16]      -- The value field associated with the Get Descriptor request.
                             Contains the descriptor type and index.
        I: length[16]     -- The length field associated with the Get Descriptor request.
                             Determines the maximum amount allowed in a response.

        I: start          -- Strobe that indicates when a descriptor should be transmitted.
        I: start_position -- Specifies the starting position of the descriptor data to be transmitted.

        *: tx             -- The USBInStreamInterface that streams our descriptor data.
        O: stall          -- Pulsed if a STALL handshake should be generated, instead of a response.
    """

    def __init__(self, descriptor_collection: DeviceDescriptorCollection, max_packet_length=64, domain="usb"):
        """
        Parameters
        ----------
        descriptor_collection: DeviceDescriptorCollection
            The DeviceDescriptorCollection containing the descriptors to use for this device.
        max_packet_length: int
            Maximum packet length.
        domain: string
            The clock domain this generator should belong to. Defaults to 'usb'.
        """

        self._descriptors = descriptor_collection
        self._max_packet_length = max_packet_length
        self._domain           = domain

        #
        # I/O port
        #
        self.value          = Signal(16)
        self.length         = Signal(16)

        self.start          = Signal()
        self.start_position = Signal(11)

        self.tx             = USBInStreamInterface()
        self.stall          = Signal()

    def generate_rom_content(self):
        """ Generates the ROM content.

        Memory layout
        -------------

        All data is aligned on 4 bytes

        Type offsets and number of entries
        ----------------------------------

        Each descriptor type starting from 0 until maximum used type number has
        an entry consisting of number of indexes for this type number (2 bytes)
        and address of first index (2 bytes).
        Invalid entries have a value of 0x0000xxxx (0 entries).

        Example:
        0000  0xFFFF
        0002  0xFFFF
        0004  Number of device indexes
        0006  Address of first device index
        0008  Number of configuration indexes
        000A  Address of first configuration index
        000C  Number of string indexes
        000E  Address of first string index
        ...

        Index offsets and length of descriptor
        --------------------------------------
        Each index of a descriptor type has an entry consistent of the length
        of the descriptor (2 bytes) and the address of first data byte (2 bytes).

        0010  Length of first device descriptor
        0012  Address of first device descriptor
        ...

        Data
        ----
        Descriptor data for each descriptor. Padded by 0 to next 4-byte address.

        ...   Descriptor data

        """

        # Get all descriptors and cache them in a dictionary, so that we can access them at will
        descriptors = {}
        for type_number, index, raw_descriptor in self._descriptors:
            if type_number not in descriptors:
                descriptors[type_number] = {}

            descriptors[type_number][index] = raw_descriptor

        self.maximum_type_number = sorted(descriptors.keys())[-1]

        # Check that indexes are continuous
        for type_number, indexes in sorted(descriptors.items()):
            assert(sorted(indexes.keys())[-1] == len(indexes) - 1)

        total_size = (# Base addresses
                      (self.maximum_type_number + 1) * 4 +
                      # Points to data
                      functools.reduce(lambda x, indexes: x + len(indexes), descriptors.values(), 0) * 4 +
                      # Actual data
                      functools.reduce(lambda x, indexes: x + functools.reduce(lambda x, raw_descriptor: x + ((len(raw_descriptor)+3)//4)*4, indexes.values(), 0), descriptors.values(), 0))

        rom = bytearray(total_size)

        # Fill ROM

        # Write type offsets and number of entries
        next_free_address = (self.maximum_type_number+1)*4
        type_index_base_address = [0] * (self.maximum_type_number+1)
        for type_number, indexes in sorted(descriptors.items()):
            type_base_address = type_number * 4
            rom[type_base_address:type_base_address + 4] = struct.pack(">HH", len(indexes), next_free_address)
            type_index_base_address[type_number] = next_free_address
            next_free_address += len(indexes) * 4

        # Write index offsets and data
        for type_number, indexes in sorted(descriptors.items()):
            for index, raw_descriptor in sorted(indexes.items()):
                index_base_address = type_index_base_address[type_number] + index * 4
                rom[index_base_address:index_base_address+4] = struct.pack(">HH", len(raw_descriptor), next_free_address)
                rom[next_free_address:next_free_address+len(raw_descriptor)] = raw_descriptor
                next_free_address += ((len(raw_descriptor)+3)//4)*4

        # for i in range(len(rom)//16+1):
        #     data = " ".join([f"{rom[16*i+j]:02X}" for j in range(16 if i < (len(rom)//16) else  len(rom)-16*i)])
        #     print(f"{i*16:04X} {data}")

        assert(total_size == len(rom))

        self.rom_content = [struct.unpack(">I", rom[4*i:4*i+4])[0] for i in range(total_size//4)]
        self.descriptor_max_length = functools.reduce(lambda x, indexes: max(x, functools.reduce(lambda x, raw_descriptor: max(x, len(raw_descriptor)), indexes.values(), 0)), descriptors.values(), 0)

    def elaborate(self, platform) -> Module:
        m = Module()

        # Aliases for type/index
        type_number = Signal(8)
        index = Signal(8)

        m.d.comb += [
            index.eq(self.value.word_select(0, 8)),
            type_number.eq(self.value.word_select(1, 8))
        ]

        # ROM
        self.generate_rom_content()
        rom = Memory(width=32, depth=len(self.rom_content), init=self.rom_content)
        m.submodules.rom_read_port = rom_read_port = rom.read_port(transparent=False)

        #
        # Figure out the maximum length we're willing to send.
        #
        length = Signal(16)

        # We'll never send more than our MaxPacketSize. This means that we'll want to send a maximum of
        # either our maximum packet length, or the amount of data we have remaining; whichever is less.
        #
        words_remaining = self.length - self.start_position
        with m.If(words_remaining <= self._max_packet_length):
            m.d.comb += length.eq(words_remaining)
        with m.Else():
            m.d.comb += length.eq(self._max_packet_length)

        # Register that stores our current position in the stream.
        position_in_stream = Signal(range(self.descriptor_max_length))
        bytes_sent = Signal.like(length)

        # Registers that store descriptor length and data base address.
        descriptor_length = Signal(16)
        descriptor_data_base_address = Signal(rom_read_port.addr.width)

        # Track when we're on the first and last packet.
        on_first_packet = position_in_stream == self.start_position
        on_last_packet = \
            (position_in_stream == (descriptor_length - 1)) | \
            (bytes_sent + 1 >= length)

        with m.FSM() as fsm:
            m.d.comb += self.tx.valid.eq(fsm.ongoing('STREAMING'))

            with m.State('IDLE'):
                m.d.comb += [
                    rom_read_port.addr.eq(type_number),
                ]
                m.d.sync += [
                    bytes_sent.eq(0)
                ]

                with m.If(self.start):
                    m.d.sync += [
                        position_in_stream.eq(self.start_position),
                    ]

                    with m.If((length > 0) & (type_number <= self.maximum_type_number)):
                        m.next = 'TYPE'
                    with m.Else():
                        m.d.comb += [
                            self.stall.eq(1)
                        ]

            with m.State('TYPE'):
                # If no entries are available for index or type number is unused, stall
                with m.If(index >= rom_read_port.data.word_select(1, 16)):
                    m.d.comb += [
                        self.stall.eq(1)
                    ]
                    m.next = "IDLE"

                with m.Else():
                    m.d.comb += [
                        rom_read_port.addr.eq(rom_read_port.data.bit_select(2, rom_read_port.addr.width)+index)
                    ]
                    m.next = 'INDEX'

            with m.State('INDEX'):
                m.d.comb += [
                   rom_read_port.addr.eq((rom_read_port.data+position_in_stream).bit_select(2, rom_read_port.addr.width))
                ]
                m.d.sync += [
                    descriptor_data_base_address.eq(rom_read_port.data.bit_select(2, descriptor_data_base_address.width)),
                    descriptor_length.eq(rom_read_port.data.word_select(1, 16))
                ]
                m.next = 'STREAMING'

            with m.State('STREAMING'):
                m.d.comb += [
                    # Always drive the stream from our current memory output...
                    rom_read_port.addr.eq(descriptor_data_base_address+position_in_stream.bit_select(2, position_in_stream.width-2)),
                    self.tx.payload.eq(rom_read_port.data.word_select(3-position_in_stream.bit_select(0, 2), 8)),

                    # ... and base First and Last based on our current position in the stream.
                    self.tx.first    .eq(on_first_packet),
                    self.tx.last     .eq(on_last_packet)
                ]

                with m.If(self.tx.ready):
                    with m.If(~on_last_packet):
                        m.d.sync += [
                            position_in_stream.eq(position_in_stream + 1),
                            bytes_sent.eq(bytes_sent + 1),
                        ]
                        m.d.comb += [
                            rom_read_port.addr.eq(descriptor_data_base_address+(position_in_stream+1).bit_select(2, position_in_stream.width-2)),
                        ]

                    # Otherwise, we've finished streaming. Return to IDLE.
                    with m.Else():
                        # Reset some values, might not be really required
                        m.d.sync += [
                            descriptor_length.eq(0),
                            descriptor_data_base_address.eq(0)
                        ]
                        m.next = 'IDLE'

        # Convert our sync domain to the domain requested by the user, if necessary.
        if self._domain != "sync":
            m = DomainRenamer({"sync": self._domain})(m)

        return m


class GetDescriptorHandlerSingleMemoryTest(LunaUSBGatewareTestCase):
    descriptors = DeviceDescriptorCollection()

    with descriptors.DeviceDescriptor() as d:
        d.bcdUSB             = 2.00
        d.idVendor           = 0x1234
        d.idProduct          = 0x4567
        d.iManufacturer      = "Manufacturer"
        d.iProduct           = "Product"
        d.iSerialNumber      = "ThisSerialNumberIsResultsInADescriptorLongerThan64Bytes"
        d.bNumConfigurations = 1

        with descriptors.ConfigurationDescriptor() as c:
            c.bmAttributes = 0xC0
            c.bMaxPower = 50

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber   = 0
                i.bInterfaceClass    = 0x02
                i.bInterfaceSubclass = 0x02
                i.bInterfaceProtocol = 0x01

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x81
                    e.bmAttributes     = 0x03
                    e.wMaxPacketSize   = 64
                    e.bInterval        = 11

    # HID Descriptor (Example E.8 of HID specification)
    descriptors.add_descriptor(b'\x09\x21\x01\x01\x00\x01\x22\x00\x32')

    FRAGMENT_UNDER_TEST = GetDescriptorHandlerSingleMemory
    FRAGMENT_ARGUMENTS = {"descriptor_collection": descriptors}

    def traces_of_interest(self):
        dut = self.dut
        return (dut.value, dut.length, dut.start_position, dut.start, dut.stall,
                dut.tx.ready, dut.tx.first, dut.tx.last, dut.tx.payload, dut.tx.valid)

    def _test_descriptor(self, type_number, index, raw_descriptor, start_position, max_length, delay_ready=0):
        """ Triggers a read and checks if correct data is transmitted. """

        # Set a defined start before starting
        yield self.dut.tx.ready.eq(0)
        yield

        # Set up request
        yield self.dut.value.word_select(1, 8).eq(type_number)  # Type
        yield self.dut.value.word_select(0, 8).eq(index)  # Index
        yield self.dut.length.eq(max_length)
        yield self.dut.start_position.eq(start_position)
        yield self.dut.tx.ready.eq(1 if delay_ready == 0 else 0)
        yield self.dut.start.eq(1)
        yield

        yield self.dut.start.eq(0)

        yield from self.wait_until(self.dut.tx.valid, timeout=100)

        if delay_ready > 0:
            for _ in range(delay_ready-1):
                yield
            yield self.dut.tx.ready.eq(1)
            yield

        max_packet_length = 64
        expected_data = raw_descriptor[start_position:]
        expected_bytes = min(len(expected_data), max_length-start_position, max_packet_length)

        for i in range(expected_bytes):
            self.assertEqual((yield self.dut.tx.first), 1 if (i == 0) else 0)
            self.assertEqual((yield self.dut.tx.last), 1 if (i == expected_bytes-1) else 0)
            self.assertEqual((yield self.dut.tx.valid), 1)
            self.assertEqual((yield self.dut.tx.payload), expected_data[i])
            self.assertEqual((yield self.dut.stall), 0)
            yield

        self.assertEqual((yield self.dut.tx.valid), 0)

    def _test_stall(self, type_number, index, start_position, max_length):
        """ Triggers a read and checks if correctly stalled. """

        yield self.dut.value.word_select(1, 8).eq(type_number)  # Type
        yield self.dut.value.word_select(0, 8).eq(index)  # Index
        yield self.dut.length.eq(max_length)
        yield self.dut.start_position.eq(start_position)
        yield self.dut.tx.ready.eq(1)
        yield self.dut.start.eq(1)
        yield

        yield self.dut.start.eq(0)

        cycles_passed = 0
        timeout = 100

        while not (yield self.dut.stall):
            self.assertEqual((yield self.dut.tx.valid), 0)
            yield

            cycles_passed += 1
            if timeout and cycles_passed > timeout:
                raise RuntimeError(f"Timeout waiting for stall!")

    @usb_domain_test_case
    def test_all_descriptors(self):
        for type_number, index, raw_descriptor in self.descriptors:
            yield from self._test_descriptor(type_number, index, raw_descriptor, 0, len(raw_descriptor))
            yield from self._test_descriptor(type_number, index, raw_descriptor, 0, len(raw_descriptor), delay_ready=10)

    @usb_domain_test_case
    def test_all_descriptors_with_offset(self):
        for type_number, index, raw_descriptor in self.descriptors:
            if len(raw_descriptor) > 1:
                yield from self._test_descriptor(type_number, index, raw_descriptor, 1, len(raw_descriptor))

    @usb_domain_test_case
    def test_all_descriptors_with_length(self):
        for type_number, index, raw_descriptor in self.descriptors:
            if len(raw_descriptor) > 1:
                yield from self._test_descriptor(type_number, index, raw_descriptor, 0, min(8, len(raw_descriptor)-1))
                yield from self._test_descriptor(type_number, index, raw_descriptor, 0, min(8, len(raw_descriptor)-1), delay_ready=10)

    @usb_domain_test_case
    def test_all_descriptors_with_offset_and_length(self):
        for type_number, index, raw_descriptor in self.descriptors:
            if len(raw_descriptor) > 1:
                yield from self._test_descriptor(type_number, index, raw_descriptor, 1, min(8, len(raw_descriptor)-1))

    @usb_domain_test_case
    def test_all_descriptors_with_zero_length(self):
        for type_number, index, raw_descriptor in self.descriptors:
            yield from self._test_stall(type_number, index, 0, 0)

    @usb_domain_test_case
    def test_unavailable_descriptor(self):
        yield from self._test_stall(StandardDescriptorNumbers.STRING, 100, 0, 64)

    @usb_domain_test_case
    def test_unavailable_index_type(self):
        # Unavailable index in between
        yield from self._test_stall(0x10, 0, 0, 64)

        # Index after last used type
        yield from self._test_stall(0x42, 0, 0, 64)

if __name__ == "__main__":
    unittest.main()
