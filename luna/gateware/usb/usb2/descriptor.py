#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Utilities for building USB descriptors into gateware. """

import struct
import unittest
import functools

from amaranth                                import *
from usb_protocol.emitters.descriptors       import DeviceDescriptorCollection
from usb_protocol.types.descriptors.standard import StandardDescriptorNumbers

from ..stream                                import USBInStreamInterface
from ...stream.generator                     import ConstantStreamGenerator
from ...test                                 import LunaUSBGatewareTestCase, usb_domain_test_case


class USBDescriptorStreamGenerator(ConstantStreamGenerator):
    """ Specialized stream generator for generating USB descriptor constants. """

    def __init__(self, data):
        """
        Parameters:
            descriptor_number -- The descriptor number represented.
            data              -- The raw bytes (or equivalent) for the descriptor.
        """

        # Always create USB descriptors in the USB domain; always have a maximum length field that can
        # be up to 16 bits wide, and always use USBInStream's. These allow us to tie easily to our request
        # handlers.
        super().__init__(data, domain="usb", stream_type=USBInStreamInterface, max_length_width=16)



class GetDescriptorHandlerDistributed(Elaboratable):
    """ Gateware that handles responding to GetDescriptor requests.

    Currently does not support descriptors in multiple languages.

    I/O port:
        I: value[16]  -- The value field associated with the Get Descriptor request.
                         Contains the descriptor type and index.
        I: length[16] -- The length field associated with the Get Descriptor request.
                         Determines the maximum amount allowed in a response.

        I: start      -- Strobe that indicates when a descriptor should be transmitted.

        *: tx         -- The USBInStreamInterface that streams our descriptor data.
        O: stall      -- Pulsed if a STALL handshake should be generated, instead of a response.
    """

    def __init__(self, descriptor_collection: DeviceDescriptorCollection, max_packet_length=64):
        """
        Parameteres:
            descriptor_collection -- The DeviceDescriptorCollection containing the descriptors
                                     to use for this device.
        """

        self._descriptors = descriptor_collection
        self._max_packet_length = max_packet_length

        #
        # I/O port
        #
        self.value          = Signal(16)
        self.length         = Signal(16)

        self.start          = Signal()
        self.start_position = Signal(11)

        self.tx             = USBInStreamInterface()
        self.stall          = Signal()


    def elaborate(self, platform):
        m = Module()

        # Collection that will store each of our descriptor-generation submodules.
        descriptor_generators = {}

        #
        # Figure out the maximum length we're willing to send.
        #
        length = Signal(16)

        # We'll never send more than our MaxPacketSize. This means that we'll want to send a maximum of
        # either our maximum packet length, or the amount of data we have remaining; whichever is less.
        #
        # Note that this doesn't take into account the length of the actual data to be sent; this is handled
        # in the stream generator.
        words_remaining = self.length - self.start_position
        with m.If(words_remaining <= self._max_packet_length):
            m.d.comb += length.eq(words_remaining)
        with m.Else():
            m.d.comb += length.eq(self._max_packet_length)


        #
        # Create our constant-stream generators for each of our descriptors.
        #
        for type_number, index, raw_descriptor in self._descriptors:
            # Create the generator...
            generator = USBDescriptorStreamGenerator(raw_descriptor)
            descriptor_generators[(type_number, index)] = generator

            m.d.comb += [
                generator.max_length     .eq(length),
                generator.start_position .eq(self.start_position)
            ]

            # ... and attach it to this module.
            type_ref =  type_number.name if isinstance(type_number, StandardDescriptorNumbers) else type_number
            setattr(m.submodules, f'USBDescriptorStreamGenerator({type_ref},{index})', generator)


        #
        # Connect up each of our generators.
        #

        with m.Switch(self.value):

            # Generate a conditional interconnect for each of our items.
            for (type_number, index), generator in descriptor_generators.items():

                # If the value matches the given type number...
                with m.Case(type_number << 8 | index):

                    # ... connect the relevant generator to our output.
                    m.d.comb += generator.stream  .attach(self.tx)
                    m.d.usb += generator.start    .eq(self.start),

            # If none of our descriptors match, stall any request that comes in.
            with m.Case():
                m.d.comb += self.stall.eq(self.start)


        return m


class GetDescriptorHandlerBlock(Elaboratable):
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

    ELEMENT_SIZE = 4

    COUNT_SIZE_BITS   = 16
    ADDRESS_SIZE_BITS = 16

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

        self._descriptors        = descriptor_collection
        self._max_packet_length  = max_packet_length
        self._domain             = domain

        #
        # I/O port
        #
        self.value          = Signal(16)
        self.length         = Signal(16)

        self.start          = Signal()
        self.start_position = Signal(11)

        self.tx             = USBInStreamInterface()
        self.stall          = Signal()


    @classmethod
    def _align_to_element_size(cls, n):
        """ Returns a given number rounded up to the next "aligned" element size. """
        return (n + (cls.ELEMENT_SIZE - 1)) // cls.ELEMENT_SIZE

    def generate_rom_content(self):
        """ Generates the contents of the ROM used to hold descriptors.

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

        # Get all descriptors and cache them in a dictionary, so that we can access them at will.
        descriptors = {}
        for type_number, index, raw_descriptor in self._descriptors:
            if type_number not in descriptors:
                descriptors[type_number] = {}

            descriptors[type_number][index] = raw_descriptor

        # For now, we only support layouts with consecutive indexes.
        # Ensure this is the case.
        for type_number, indexes in sorted(descriptors.items()):
            assert max(indexes.keys()) == len(indexes) - 1, "descriptors have non-contiguous indices!"


        #
        # Compute the ROM size that we'll need.
        #
        max_type_number         = max(descriptors.keys())
        max_descriptor_size     = 0

        # Our ROM starts with a collection of pointers to our various descriptor tables...
        rom_size_table_pointers = (max_type_number + 1) * self.ELEMENT_SIZE

        # ... tables of pointers to each actual descriptor...
        table_entry_count = functools.reduce(lambda x, indexes: x + len(indexes), descriptors.values(), 0)
        rom_size_table_entries = table_entry_count * self.ELEMENT_SIZE

        # ... and the descriptors themselves.
        rom_size_descriptors = 0
        for descriptor_set in descriptors.values():
            for raw_descriptor in descriptor_set.values():

                # Compute the maximum size for each descriptor...
                aligned_size = self._align_to_element_size(len(raw_descriptor))
                rom_size_descriptors += aligned_size * self.ELEMENT_SIZE

                # ... and store the maximum size we've encountered.
                max_descriptor_size = max(max_descriptor_size, len(raw_descriptor))

        # Create an array to hold our initial values for our composite ROM.
        total_size = \
            rom_size_table_pointers + \
            rom_size_table_entries  + \
            rom_size_descriptors
        rom = bytearray(total_size)

        #
        # Fill the ROM's initialization values.
        #
        next_free_address       = (max_type_number + 1) * self.ELEMENT_SIZE
        type_index_base_address = [0] * (max_type_number + 1)

        # First, generate a list of "table pointers", which point to the address of each type, in memory.
        for type_number, indexes in sorted(descriptors.items()):

            # Create our table pointer entry, which should always point to the next free address...
            pointer_bytes = struct.pack(">HH", len(indexes), next_free_address)

            # ...add the pointer to our ROM...
            type_base_address = type_number * self.ELEMENT_SIZE
            rom[type_base_address:type_base_address + self.ELEMENT_SIZE] = pointer_bytes

            # ... store the base address, for our subsequent fill...
            type_index_base_address[type_number] = next_free_address

            #... and move to the next entry.
            next_free_address += len(indexes) * self.ELEMENT_SIZE


        # Next, create the tables themselves, which are filled with data pointers,
        # and add our descriptors to our memory.
        for type_number, descriptor_set in sorted(descriptors.items()):
            for index, raw_descriptor in sorted(descriptor_set.items()):

                # Create our descriptor pointer entries...
                pointer_bytes = struct.pack(">HH", len(raw_descriptor), next_free_address)

                # ... figure out where in the ROM we're going to store the pointer ...
                index_base_address = type_index_base_address[type_number] + index * self.ELEMENT_SIZE

                # ... add the pointer...
                rom[index_base_address:index_base_address + 4] = pointer_bytes

                # ... and then store the descriptor itself to the pointer address.
                rom[next_free_address:next_free_address+len(raw_descriptor)] = raw_descriptor

                # Figure out the next free position for a descriptor.
                aligned_size = self._align_to_element_size(len(raw_descriptor))
                next_free_address += aligned_size * self.ELEMENT_SIZE

        assert total_size == len(rom)


        #
        # Finally, convert our ROM into an initialization vector.
        #
        total_elements = total_size // self.ELEMENT_SIZE
        element_size = self.ELEMENT_SIZE

        # Chunk our ROM into a collection of entries...
        rom_entries = (rom[(element_size * i):(element_size * i) + element_size] for i in range(total_elements))

        # ... and then convert that into an initializer value in the format Amaranth ROMs like (integers).
        initializer = [struct.unpack(">I", rom_entry)[0] for rom_entry in rom_entries]

        return initializer, max_descriptor_size, max_type_number


    def elaborate(self, platform) -> Module:
        m = Module()

        # Aliases for type/index
        type_number = Signal(8)
        index = Signal(8)

        m.d.comb += [
            index.eq(self.value.word_select(0, 8)),
            type_number.eq(self.value.word_select(1, 8))
        ]

        #
        # Create the ROM that stores our descriptors...
        #
        rom_content, descriptor_max_length, max_type_index = self.generate_rom_content()

        rom = Memory(width=32, depth=len(rom_content), init=rom_content)
        m.submodules.rom_read_port = rom_read_port = rom.read_port(transparent=False)

        # Create convenience aliases to the upper and lower half of the ROM.
        rom_upper_half = rom_read_port.data.word_select(1, 16)
        rom_lower_half = rom_read_port.data.word_select(0, 16)

        # All of our ROM's metadata is composed of elements formatted as (count, pointer).
        # Grab a quick reference to the ROM's upper half, which stores the count...
        rom_element_count    = rom_upper_half

        # ... and to the ROM's lower half, not counting the last two bits (which are always 0,
        # as our pointers are always aligned). This creates an element pointer counted in words,
        # instead of in bytes; and thus one compatible with our read_port addr.
        rom_element_pointer  = rom_read_port.data.bit_select(2, rom_read_port.addr.width)

        #
        # Figure out the maximum length we're willing to send.
        #
        length = Signal(16)

        # We'll never send more than our MaxPacketSize. This means that we'll want to send a maximum of
        # either our maximum packet length, or the amount of data we have remaining; whichever is less.
        #
        words_remaining = self.length - self.start_position
        with m.If(words_remaining <= self._max_packet_length):
            m.d.sync += length.eq(words_remaining)
        with m.Else():
            m.d.sync += length.eq(self._max_packet_length)

        # Register that stores our current position in the stream.
        position_in_stream = Signal(range(descriptor_max_length))
        bytes_sent = Signal.like(length)

        # Registers that store descriptor length and data base address.
        descriptor_length = Signal(16)
        descriptor_data_base_address = Signal(rom_read_port.addr.width)

        # Track when we're on the first and last packet.
        on_first_packet = position_in_stream == self.start_position
        on_last_packet = \
            (position_in_stream == (descriptor_length - 1)) | \
            (bytes_sent + 1 >= length)

        #
        # Core transmit logic.
        #

        with m.FSM():

            # IDLE -- we're currently waiting to send a descriptor.
            with m.State('IDLE'):

                # Reset our data-sent count...
                m.d.sync += bytes_sent.eq(0)

                # ... and always prepare to read whatever descriptor type is requested.
                m.d.comb += rom_read_port.addr.eq(type_number)

                # Once we have a request to start transmitting...
                with m.If(self.start):
                    m.next = 'START'

            # START -- retiming state to allow construction of the length signal
            with m.State('START'):
                # ... and always prepare to read whatever descriptor type is requested.
                m.d.comb += rom_read_port.addr.eq(type_number)

                # ... apply our start position...
                m.d.sync += position_in_stream.eq(self.start_position),

                is_valid_type = (type_number <= max_type_index)

                # If we have a descriptor we're able to send, prepare to send it.
                with m.If(is_valid_type):
                    m.next = 'LOOKUP_TYPE'

                # Otherwise, stall the request immediately.
                with m.Else():
                    m.d.comb += self.stall.eq(1)
                    m.next = 'IDLE'

            # LOOKUP_TYPE -- we're now ready to start sending a descriptor, but we've not yet fetched the
            # descriptor from memory. First, we'll need to find the location of the table that contains each
            # descriptor pointer.
            with m.State('LOOKUP_TYPE'):

                # Our previous state already selected the ROM word associated with our "table of tables";
                # meaning the ROM's read port now contains (count, table-pointer) for the relevant ROM type.

                # If the requested type is greater than the maximum type number the ROM encodes,
                # stall the request and return to idle.
                with m.If(index >= rom_element_count):
                    m.d.comb += self.stall.eq(1)
                    m.next = "IDLE"

                # Otherwise, look up the type data in the ROM; and then move on to finding the descriptor itself.
                with m.Else():
                    m.d.comb += rom_read_port.addr.eq(rom_element_pointer + index)
                    with m.If(length == 0):
                        m.next = 'SEND_ZLP'
                    with m.Else():
                        m.next = 'LOOKUP_DESCRIPTOR'


            # LOOKUP_DESCRIPTOR -- we've now fetched from ROM the location of the descriptor in memory.
            # We'll decode it, and then prepare to start sending the descriptor.
            # descriptor from memory. First, we'll need to find the location of the table that contains each
            # descriptor pointer.
            with m.State('LOOKUP_DESCRIPTOR'):

                # Point our descriptor at the first word in our descriptor, offset by our current position
                # in the stream...
                m.d.comb += rom_read_port.addr.eq((rom_read_port.data + position_in_stream) >> 2)

                # ... and register the position and shape of our descriptor in memory.
                m.d.sync += [
                    descriptor_data_base_address  .eq(rom_element_pointer),
                    descriptor_length             .eq(rom_element_count),
                ]

                m.next = 'SEND_DESCRIPTOR'


            # SEND_DESCRIPTOR -- we finally are actively streaming our descriptor; which we'll complete until
            # our descriptor is fully sent.
            with m.State('SEND_DESCRIPTOR'):
                word_in_stream = position_in_stream >> 2
                byte_in_stream = position_in_stream.bit_select(0, 2)

                m.d.comb += [
                    self.tx.valid       .eq(1),

                    # Always drive the stream from our current memory output...
                    rom_read_port.addr  .eq(descriptor_data_base_address + word_in_stream),
                    self.tx.payload     .eq(rom_read_port.data.word_select(3 - byte_in_stream, 8)),

                    # ... and base First and Last based on our current position in the stream.
                    self.tx.first       .eq(on_first_packet),
                    self.tx.last        .eq(on_last_packet)
                ]

                # Once a given word is accepted, we're ready to move on.
                with m.If(self.tx.ready):

                    # If we're not yet done, move to the next byte in the stream.
                    with m.If(~on_last_packet):
                        m.d.sync += [
                            position_in_stream  .eq(position_in_stream + 1),
                            bytes_sent          .eq(bytes_sent + 1),
                        ]
                        m.d.comb += rom_read_port.addr.eq(descriptor_data_base_address+(position_in_stream + 1).bit_select(2, position_in_stream.width - 2)),

                    # Otherwise, we've finished! Return to IDLE.
                    with m.Else():
                        # Reset some values, might not be really required
                        m.d.sync += [
                            descriptor_length             .eq(0),
                            descriptor_data_base_address  .eq(0)
                        ]
                        m.next = 'IDLE'

            # SEND_ZLP -- we've had an empty descriptor request, or a request that ended on a packet boundary.
            # Send a zero-length packet to end the transaction.
            with m.State('SEND_ZLP'):
                m.d.comb += [
                    # Pulse `last` without `first` to indicate a ZLP.
                    self.tx.valid.eq(1),
                    self.tx.last .eq(1),
                ]
                m.next = 'IDLE'


        # Convert our sync domain to the domain requested by the user, if necessary.
        if self._domain != "sync":
            m = DomainRenamer({"sync": self._domain})(m)

        return m


class GetDescriptorHandlerBlockTest(LunaUSBGatewareTestCase):
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

    FRAGMENT_UNDER_TEST = GetDescriptorHandlerBlock
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

        if expected_bytes == 0:
            self.assertEqual((yield self.dut.tx.first), 0)
            self.assertEqual((yield self.dut.tx.last),  1)
            self.assertEqual((yield self.dut.tx.valid), 1)
            self.assertEqual((yield self.dut.stall),    0)
            yield

        else:
            for i in range(expected_bytes):
                self.assertEqual((yield self.dut.tx.first),   1 if (i == 0) else 0)
                self.assertEqual((yield self.dut.tx.last),    1 if (i == expected_bytes - 1) else 0)
                self.assertEqual((yield self.dut.tx.valid),   1)
                self.assertEqual((yield self.dut.tx.payload), expected_data[i])
                self.assertEqual((yield self.dut.stall),      0)
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
            yield from self._test_descriptor(type_number, index, raw_descriptor, 0, 0)

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
