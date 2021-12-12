#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import math

from enum      import Enum
from functools import reduce
from operator  import or_

from amaranth     import Elaboratable, Record, Module, Cat, Array, Repl, Signal, Memory
from amaranth_soc import wishbone, memory


class WishboneRAM(Elaboratable):
    """ Simple Wishbone-connected RAM. """


    @staticmethod
    def _initialization_value(value, data_width, granularity, byteorder):
        """ Converts a provided value into a valid Memory-initializer array.

        Parameters should match those provied to __init__
        """

        # If this is a filename, read the file's contents before processing.
        if isinstance(value, str):
            with open(value, "rb") as f:
                value = f.read()

        # If we don't have bytes, read this direction.
        if not isinstance(value, bytes):
            return value

        bytes_per_chunk = data_width // granularity

        words = (value[pos:pos + bytes_per_chunk] for pos in range(0, len(value), bytes_per_chunk))
        return [int.from_bytes(word, byteorder=byteorder) for word in words]



    def __init__(self, *, addr_width, data_width=32, granularity=8, init=None,
            read_only=False, byteorder="little", name="ram"):
        """
        Parameters:
            addr_width  -- The -bus- address width for the relevant memory. Determines the size
                           of the memory.
            data_width  -- The width of each memory word.
            granularity -- The number of bits of data per each address.
            init        -- Optional. The initial value of the relevant memory. Should be an array of integers, a
                           filename, or a bytes-like object. If bytes are provided, the byteorder parametera allows
                           control over their interpretation. If a filename is provided, this filename will not be read
                           until elaboration; this allows reading the file to be deferred until the very last minute in
                           e.g. systems that generate the relevant file during build.
            read_only   -- If true, this will ignore writes to this memory, so it effectively
                           acts as a ROM fixed to its initialization value.
            byteorder   -- Sets the byte order of the initializer value. Ignored unless a bytes-type initializer is provided.
            name        -- A descriptive name for the given memory.
        """

        self.name          = name
        self.read_only     = read_only
        self.data_width    = data_width
        self.initial_value = init
        self.byteorder     = byteorder

        # Our granularity determines how many bits of data exist per single address.
        # Often, this isn't the same as our data width; which means we'll wind up with
        # two different address widths: a 'local' one where each address corresponds to a
        # data value in memory; and a 'bus' one where each address corresponds to a granularity-
        # sized chunk of memory.
        self.granularity   = granularity
        self.bus_addr_width = addr_width

        # Our bus addresses are more granular than our local addresses.
        # Figure out how many more bits exist in our bus addresses, and use
        # that to figure out our local bus size.
        self.bytes_per_word   = data_width // granularity
        self.bits_in_bus_only = int(math.log2(self.bytes_per_word))
        self.local_addr_width = self.bus_addr_width - self.bits_in_bus_only

        # Create our wishbone interface.
        # Note that we provide the -local- address to the Interface object; as it automatically factors
        # in our extra bits as it computes our granularity.
        self.bus = wishbone.Interface(addr_width=self.local_addr_width, data_width=data_width, granularity=granularity)
        self.bus.memory_map = memory.MemoryMap(addr_width=self.bus_addr_width, data_width=granularity)
        self.bus.memory_map.add_resource(self, size=2 ** addr_width)


    def elaborate(self, platform):
        m = Module()

        # Create our memory initializer from our initial value.
        initial_value = self._initialization_value(self.initial_value, self.data_width, self.granularity, self.byteorder)

        # Create the the memory used to store our data.
        memory_depth = 2 ** self.local_addr_width
        memory = Memory(width=self.data_width, depth=memory_depth, init=initial_value, name=self.name)

        # Grab a reference to the bits of our Wishbone bus that are relevant to us.
        local_address_bits = self.bus.adr[:self.local_addr_width]

        # Create a read port, and connect it to our Wishbone bus.
        m.submodules.rdport = read_port = memory.read_port()
        m.d.comb += [
            read_port.addr.eq(local_address_bits),
            self.bus.dat_r.eq(read_port.data)
        ]

        # If this is a read/write memory, create a write port, as well.
        if not self.read_only:
            m.submodules.wrport = write_port = memory.write_port(granularity=self.granularity)
            m.d.comb += [
                write_port.addr.eq(local_address_bits),
                write_port.data.eq(self.bus.dat_w)
            ]

            # Generate the write enables for each of our words.
            for i in range(self.bytes_per_word):
                m.d.comb += write_port.en[i].eq(
                    self.bus.cyc &    # Transaction is active.
                    self.bus.stb &    # Valid data is being provided.
                    self.bus.we  &    # This is a write.
                    self.bus.sel[i]   # The relevant setion of the datum is being targeted.
                )


        # We can handle any transaction request in a single cycle, when our RAM handles
        # the read or write. Accordingly, we'll ACK the cycle after any request.
        m.d.sync += self.bus.ack.eq(
            self.bus.cyc &
            self.bus.stb &
            ~self.bus.ack
        )

        return m


class WishboneROM(WishboneRAM):
    """ Wishbone-attached ROM. """

    def __init__(self, data, *, addr_width, data_width=32, granularity=8, name="rom"):
        """
        Parameters:
            data -- The data to fill the ROM with.

            addr_width  -- The -bus- address width for the relevant memory. Determines the address size of the memory.
                           Physical size is based on the data provided, as unused elements will be optimized away.
            data_width  -- The width of each memory word.
            granularity -- The number of bits of data per each address.
            name        -- A descriptive name for the ROM.
        """

        super().__init__(
            addr_width=addr_width,
            data_width=data_width,
            granularity=8,
            init=data,
            read_only=True,
            name=name
        )
