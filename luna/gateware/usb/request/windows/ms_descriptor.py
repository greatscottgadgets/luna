#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import struct

from amaranth                                     	import DomainRenamer, Elaboratable, Memory, Module, Signal
from usb_protocol.emitters.descriptors.microsoft10 	import MicrosoftOS10DescriptorCollection

from ...stream                                    	import USBInStreamInterface


class GetMicrosoftDescriptorHandlerBlock(Elaboratable):
    """ Gateware that handles responding to GET_MS_DESCRIPTOR requests.

    I/O port:
        I: request[8]     -- The index field associated with the GET_MS_DESCRIPTOR request.
        I: length[16]     -- The length field associated with the GET_MS_DESCRIPTOR request.
                             Determines the maximum amount allowed in a response.

        I: start          -- Strobe that indicates when a descriptor should be transmitted.
        I: start_position -- Specifies the starting position of the descriptor data to be transmitted.

        *: tx             -- The USBInStreamInterface that streams our descriptor data.
        O: stall          -- Pulsed if a STALL handshake should be generated, instead of a response.
    """

    ELEMENT_SIZE = 4

    COUNT_SIZE_BITS   = 16
    ADDRESS_SIZE_BITS = 16

    def __init__(self, descriptor_collection: MicrosoftOS10DescriptorCollection, max_packet_length=64, domain="usb"):
        """
        Parameters
        ----------
        descriptor_collection: MicrosoftOS10DescriptorCollection
            The MicrosoftOS10DescriptorCollection containing the descriptors to use for this device.
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
        self.index          = Signal(8)
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
        for index, raw_descriptor in self._descriptors:
            descriptors[index] = raw_descriptor

        # For now, we only support layouts with consecutive indexes.
        # Ensure this is the case.
        assert max(descriptors.keys()) - min(descriptors.keys()) == len(descriptors) - 1, \
            "descriptors have non-contiguous indices!"

        #
        # Compute the ROM size that we'll need.
        #
        max_index_number        = max(descriptors.keys())
        min_index_number        = min(descriptors.keys())
        indexes_count           = max_index_number - min_index_number + 1
        max_descriptor_size     = 0

        # Our ROM starts with a collection of pointers to our various descriptor tables...
        rom_size_table_pointers = indexes_count * self.ELEMENT_SIZE

        # ... and the descriptors themselves.
        rom_size_descriptors = 0
        for raw_descriptor in descriptors.values():

            # Compute the maximum size for each descriptor...
            aligned_size = self._align_to_element_size(len(raw_descriptor))
            rom_size_descriptors += aligned_size * self.ELEMENT_SIZE

            # ... and store the maximum size we've encountered.
            max_descriptor_size = max(max_descriptor_size, len(raw_descriptor))

        # Create an array to hold our initial values for our composite ROM.
        total_size = \
            rom_size_table_pointers + \
            rom_size_descriptors
        rom = bytearray(total_size)

        #
        # Fill the ROM's initialization values.
        #
        next_free_address       = rom_size_table_pointers

        # Next, create the tables themselves, which are filled with data pointers,
        # and add our descriptors to our memory.
        for index, raw_descriptor in sorted(descriptors.items()):

            # Create our descriptor pointer entries...
            pointer_bytes = struct.pack(">HH", len(raw_descriptor), next_free_address)

            # ... figure out where in the ROM we're going to store the pointer ...
            index_base_address = (index - min_index_number) * self.ELEMENT_SIZE

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

        return initializer, max_descriptor_size, max_index_number, min_index_number


    def elaborate(self, platform):
        m = Module()

        index = self.index

        #
        # Create the ROM that stores our descriptors...
        #
        rom_content, descriptor_max_length, max_index, min_index = self.generate_rom_content()

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
        # We still want to be able to store a position beyond bounds (+1),
        # this is required for descriptors length multiple of the maximum packet size.
        # Like this we do not overflow our position and are able to send a ZLP on the next request.
        position_in_stream = Signal(range(descriptor_max_length + 1))
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
                m.d.comb += rom_read_port.addr.eq(index - min_index)

                # Once we have a request to start transmitting...
                with m.If(self.start):
                    m.next = 'START'

            # START -- retiming state to allow construction of the length signal
            with m.State('START'):
                # ... and always prepare to read whatever descriptor type is requested.
                m.d.comb += rom_read_port.addr.eq(index - min_index)

                # ... apply our start position...
                m.d.sync += position_in_stream.eq(self.start_position),

                is_valid_index = (min_index <= index) & (index <= max_index)

                # If we have a descriptor we're able to send, prepare to send it.
                with m.If(is_valid_index):
                    m.next = 'LOOKUP_DESCRIPTOR'

                # Otherwise, stall the request immediately.
                with m.Else():
                    m.d.comb += self.stall.eq(1)
                    m.next = 'IDLE'


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

                # Our current position may point out of bounds in case our descriptor length is a multiple
                # of the maximum packet size. We must send a ZLP now so the host knows the previous
                # packet was the end of the descriptor.
                with m.If(rom_element_count == 0):
                    m.d.comb += self.stall.eq(1)
                    m.next = 'IDLE'
                with m.Elif(position_in_stream >= rom_element_count):
                    m.next = 'SEND_ZLP'
                with m.Else():
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
                    self.tx.payload     .eq(rom_read_port.data.word_select(~byte_in_stream, 8)),

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