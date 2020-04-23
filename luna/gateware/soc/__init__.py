#
# This file is part of LUNA.
#

import datetime

from nmigen                  import Elaboratable, Module
from nmigen_soc              import wishbone
from nmigen_soc.memory       import MemoryMap

from lambdasoc.soc.cpu       import CPUSoC
from lambdasoc.cpu.minerva   import MinervaCPU
from lambdasoc.periph.intc   import GenericInterruptController
from lambdasoc.periph.serial import AsyncSerialPeripheral
from lambdasoc.periph.sram   import SRAMPeripheral
from lambdasoc.periph.timer  import TimerPeripheral

from .memory                 import WishboneRAM, WishboneROM


class SimpleSoC(CPUSoC, Elaboratable):
    """ Class used for building simple, example system-on-a-chip architectures.

    Intended to facilitate demonstrations (and very simple USB devices) by providing
    a wrapper that can be updated as the nMigen-based-SoC landscape changes. Hopefully,
    this will eventually be filled by e.g. nMigen-compatible-LiteX. :)

    SimpleSoC devices intergrate:
        - A simple riscv32i processor.
        - One or more read-only or read-write memories.
        - A number of nmigen-soc peripherals.


    The current implementation uses a single, 32-bit wide Wishbone bus
    as the system's backend; and uses lambdasoc as its backing technology.
    This is subject to change.
    """

    BUS_ADDRESS_WIDTH = 30

    def __init__(self):
        self.peripherals = []
        self.submodules  = []

        self._rom = None
        self._ram = None

        # Create our bus decoder in advance; this allows us to build our memory map -as- peripherals
        # are added; this in turn allows us to generate build artifacts based on that memory map without
        # fully elaborating the design.
        self.bus_decoder = wishbone.Decoder(addr_width=30, data_width=32, granularity=8, features={"cti", "bte"})


    def add_rom(self, data, size, addr=0, is_main_rom=True):
        """ Creates a simple ROM and adds it to the design.

        Parameters:
            data -- The data to fill the relevant ROM.
            size -- The size for the rom that should be created.
            addr -- The address at which the ROM should reside.
            """

        # Figure out how many address bits we'll need to address the given memory size.
        addr_width = (size - 1).bit_length()

        rom = WishboneROM(data, addr_width=addr_width)
        if self._rom is None and is_main_rom:
            self._rom = rom

        return self.add_peripheral(rom, addr=addr)


    def add_ram(self, size: int, addr: int = None, is_main_mem: bool = True):
        """ Creates a simple RAM and adds it to our design.

        Parameters:
            size -- The size of the RAM, in bytes. Will be rounded up to the nearest power of two.
            addr -- The address at which to place the RAM.
        """

        # Figure out how many address bits we'll need to address the given memory size.
        addr_width = (size - 1).bit_length()

        # ... and add it as a peripheral.
        ram = WishboneRAM(addr_width=addr_width)
        if self._ram is None and is_main_mem:
            self._ram = ram

        return self.add_peripheral(ram, addr=addr)


    def add_peripheral(self, p, **kwargs):
        """ Adds a peripheral to the SoC.

        For now, this is identical to adding a peripheral to the SoC's wishbone bus.
        For convenience, returns the peripheral provided.
        """

        # Add the peripheral to our bus...
        interface = getattr(p, 'bus')
        self.bus_decoder.add(interface, **kwargs)

        # ... and keep track of it for later.
        self.peripherals.append(p)
        return p


    def elaborate(self, platform):
        m = Module()

        next_irq_index = 0

        # Add our core CPU, and create its main system bus.
        # Note that our default implementation uses a single bus for code and data,
        # so this is both the instruction bus (ibus) and data bus (dbus).
        m.submodules.cpu = cpu = MinervaCPU()
        m.submodules.bus = bus = self.bus_decoder

        # Create a basic programmable interrupt controller for our CPU.
        m.submodules.pic = pic = GenericInterruptController(width=len(cpu.ip))

        # Add each of our peripherals to the bus.
        for peripheral in self.peripherals:

            # ... add its IRQs to the IRQ controller...
            try:
                irq_line = getattr(peripheral, 'irq')
                pic.add_irq(irq_line, next_irq_index)

                next_irq_index += 1
            except (AttributeError, NotImplementedError):

                # If the object has no associated IRQs, continue anyway.
                # This allows us to add devices with only Wishbone interfaces to our SoC.
                pass

            # ... and include it in the processor.
            m.submodules += peripheral

        # Merge the CPU's data and instruction busses. This essentially means taking the two
        # separate bus masters (the CPU ibus master and the CPU dbus master), and connecting them
        # to an arbiter, so they both share use of the single bus.

        # Create the arbiter around our main bus...
        m.submodules.bus_arbiter = arbiter = wishbone.Arbiter(addr_width=30, data_width=32, granularity=8, features={"cti", "bte"})
        m.d.comb += arbiter.bus.connect(bus.bus)

        # ... and connect it to the CPU instruction and data busses.
        arbiter.add(cpu.ibus)
        arbiter.add(cpu.dbus)

        return m



    def resources(self):
        """ Creates an iterator over each of the device's addressable resources.

        Yields (resource, address, size) for each resource.
        """

        # Grab the memory map for this SoC...
        memory_map = self.bus_decoder.bus.memory_map

        # ... find each addressable peripheral...
        for peripheral, (peripheral_start, _end, _granularity) in memory_map.windows():
            resources = peripheral.all_resources()

            # ... find the peripheral's resources...
            for resource, (register_offset, register_end_offset, _local_granularity) in resources:

                # ... and extract the peripheral's range/vitals...
                size = register_end_offset - register_offset
                yield resource, peripheral_start + register_offset, size



    def _range_for_peripheral(self, target_peripheral):
        """ Returns size information for the given peripheral.

        Returns:
            addr, size -- if the given size is known; or
            None, None    if not
        """


        # Grab the memory map for this SoC...
        memory_map = self.bus_decoder.bus.memory_map

        # Search our memory map for the target peripheral.
        for peripheral, (start, end, _granularity) in memory_map.all_resources():
            if peripheral is target_peripheral:
                return start, (end - start)

        return None, None


    def generate_c_header(self, macro_name="SOC_RESOURCES", file=None):
        """ Generates a C header file that simplifies access to the platform's resources.

        Parameters:
            macro_name -- Optional. The name of the guard macro for the C header, as a string without spaces.
            file       -- Optional. If provided, this will be treated as the file= argument to the print()
                          function. This can be used to generate file content instead of printing to the terminal.
        """

        def emit(content):
            """ Utility function that emits a string to the targeted file. """
            print(content, file=file)

        # Create a mapping that maps our register sizes to C types.
        types_for_size = {
            4: 'uint32_t',
            2: 'uint16_t',
            1: 'uint8_t'
        }

        # Emit a warning header.
        emit("/*")
        emit(" * Automatically generated by LUNA; edits will be discarded on rebuild.")
        emit(" * (Most header files phrase this 'Do not edit.'; be warned accordingly.)")
        emit(" *")
        emit(f" * Generated: {datetime.datetime.now()}.")
        emit(" */")
        emit("\n")

        emit(f"#ifndef __{macro_name}_H__")
        emit(f"#define __{macro_name}_H__")
        emit("")
        emit("#include <stdint.h>\n")

        for resource, address, size in self.resources():

            # Always generate a macro for the resource's ADDRESS and size.
            name = resource.name
            emit(f"#define {name.upper()}_ADDRESS (0x{address:08x}U)")
            emit(f"#define {name.upper()}_SIZE ({size})")

            # If we have information on how to access this resource, generate convenience
            # macros for reading and writing it.
            if hasattr(resource, 'access'):
                c_type = types_for_size[size]

                # Generate a read stub, if useful...
                if resource.access.readable():
                    emit(f"static inline {c_type} {name}_read(void) {{")
                    emit(f"    volatile {c_type} *reg = ({c_type} *){name.upper()}_ADDRESS;")
                    emit(f"    return *reg;")
                    emit(f"}}")

                # ... and a write stub.
                if resource.access.writable():
                    emit(f"static inline void {name}_write({c_type} value) {{")
                    emit(f"    volatile {c_type} *reg = ({c_type} *){name.upper()}_ADDRESS;")
                    emit(f"    *reg = value;")
                    emit(f"}}")

        emit("")
        emit("#endif")
        emit("")


    def generate_ld_script(self, file=None):
        """ Generates an ldscript that holds our primary RAM and ROM regions.

        Parameters:
            file       -- Optional. If provided, this will be treated as the file= argument to the print()
                          function. This can be used to generate file content instead of printing to the terminal.
        """

        def emit(content):
            """ Utility function that emits a string to the targeted file. """
            print(content, file=file)


        # Insert our automatically generated header.
        emit("/**")
        emit(" * Linker memory regions.")
        emit("")
        emit(" * Automatically generated by LUNA; edits will be discarded on rebuild.")
        emit(" * (Most header files phrase this 'Do not edit.'; be warned accordingly.)")
        emit(" *")
        emit(f" * Generated: {datetime.datetime.now()}.")
        emit(" */")
        emit("")

        emit("MEMORY")
        emit("{")

        # Add regions for our main ROM and our main RAM.
        for memory in [self._rom, self._ram]:

            # Figure out our fields: a region name, our start, and our size.
            name = "ram" if (memory is self._ram) else "rom"
            start, size = self._range_for_peripheral(memory)

            if size:
                emit(f"    {name} : ORIGIN = 0x{start:08x}, LENGTH = {size:08x}")

        emit("}")
        emit("")
