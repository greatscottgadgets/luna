#
# This file is part of LUNA.
#
""" Simple SoC abstraction for LUNA examples."""

import os
import datetime
import logging

from nmigen                  import Elaboratable, Module
from nmigen_soc              import wishbone

from lambdasoc.soc.cpu       import CPUSoC
from lambdasoc.cpu.minerva   import MinervaCPU
from lambdasoc.periph.intc   import GenericInterruptController
from lambdasoc.periph.serial import AsyncSerialPeripheral
from lambdasoc.periph.sram   import SRAMPeripheral
from lambdasoc.periph.timer  import TimerPeripheral

from .memory                 import WishboneRAM, WishboneROM
from ..utils.cdc             import synchronize


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

    def __init__(self, clock_frequency=int(60e6)):
        """
        Parameters:
            clock_frequency -- The frequency of our `sync` domain, in MHz.
        """

        self.clk_freq = clock_frequency

        self._main_rom  = None
        self._main_ram  = None
        self._uart_baud = None

        # Keep track of our created peripherals and interrupts.
        self._submodules     = []
        self._irqs           = {}
        self._next_irq_index = 0

        # By default, don't attach any debug hardware; or build a BIOS.
        self._auto_debug = False
        self._build_bios = False

        #
        # Create our core hardware.
        # We'll create this hardware early, so it can be used for e.g. code generation without
        # fully elaborating our design.
        #

        # Create our CPU.
        self.cpu = MinervaCPU(with_debug=True)

        # Create our interrupt controller.
        self.intc = GenericInterruptController(width=32)

        # Create our bus decoder and set up our memory map.
        self.bus_decoder = wishbone.Decoder(addr_width=30, data_width=32, granularity=8, features={"cti", "bte"})
        self.memory_map  = self.bus_decoder.bus.memory_map



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
        if self._main_rom is None and is_main_rom:
            self._main_rom = rom

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
        if self._main_ram is None and is_main_mem:
            self._main_ram = ram

        return self.add_peripheral(ram, addr=addr)


    def add_peripheral(self, p, *, as_submodule=True, **kwargs):
        """ Adds a peripheral to the SoC.

        For now, this is identical to adding a peripheral to the SoC's wishbone bus.
        For convenience, returns the peripheral provided.
        """

        # Add the peripheral to our bus...
        interface = getattr(p, 'bus')
        self.bus_decoder.add(interface, **kwargs)

        # ... add its IRQs to the IRQ controller...
        try:
            irq_line = getattr(p, 'irq')
            self.intc.add_irq(irq_line, self._next_irq_index)

            self._irqs[self._next_irq_index] = p
            self._next_irq_index += 1
        except (AttributeError, NotImplementedError):

            # If the object has no associated IRQs, continue anyway.
            # This allows us to add devices with only Wishbone interfaces to our SoC.
            pass

        # ... and keep track of it for later.
        if as_submodule:
            self._submodules.append(p)

        return p


    def add_debug_port(self):
        """ Adds an automatically-connected Debug port to our SoC. """
        self._auto_debug = True


    def add_bios_and_peripherals(self, uart_pins, uart_baud_rate=115200):
        """ Adds a simple BIOS that allows loading firmware, and the requisite peripherals.

        Automatically adds the following peripherals:
            self.uart      -- An AsyncSerialPeripheral used for serial I/O.
            self.timer     -- A TimerPeripheral used for BIOS timing.
            self.rom       -- A ROM memory used for the BIOS.
            self.ram       -- The RAM used by the BIOS; not typically the program RAM.

        Parameters:
            uart_pins      -- The UARTResource to be used for UART communications; or an equivalent record.
            uart_baud_rate -- The baud rate to be used by the BIOS' uart.
        """

        self._build_bios = True
        self._uart_baud  = uart_baud_rate

        # Add our RAM and ROM.
        # Note that these names are from CPUSoC, and thus must not be changed.
        #
        # Here, we're using SRAMPeripherals instead of our more flexible ones,
        # as that's what the lambdasoc BIOS expects. These are effectively internal.
        #
        self.rom = SRAMPeripheral(size=0x4000, writable=False)
        self.add_peripheral(self.rom)

        self.ram = SRAMPeripheral(size=0x1000)
        self.add_peripheral(self.ram)

        # Add our UART and Timer.
        # Again, names are fixed.
        self.timer = TimerPeripheral(width=32)
        self.add_peripheral(self.timer)

        self.uart = AsyncSerialPeripheral(divisor=int(self.clk_freq // uart_baud_rate), pins=uart_pins)
        self.add_peripheral(self.uart)



    def elaborate(self, platform):
        m = Module()

        # Add our core CPU, and create its main system bus.
        # Note that our default implementation uses a single bus for code and data,
        # so this is both the instruction bus (ibus) and data bus (dbus).
        m.submodules.cpu = self.cpu
        m.submodules.bus = self.bus_decoder

        # Create a basic programmable interrupt controller for our CPU.
        m.submodules.pic = self.intc

        # Add each of our peripherals to the bus.
        for peripheral in self._submodules:
            m.submodules += peripheral

        # Merge the CPU's data and instruction busses. This essentially means taking the two
        # separate bus masters (the CPU ibus master and the CPU dbus master), and connecting them
        # to an arbiter, so they both share use of the single bus.

        # Create the arbiter around our main bus...
        m.submodules.bus_arbiter = arbiter = wishbone.Arbiter(addr_width=30, data_width=32, granularity=8, features={"cti", "bte"})
        m.d.comb += arbiter.bus.connect(self.bus_decoder.bus)

        # ... and connect it to the CPU instruction and data busses.
        arbiter.add(self.cpu.ibus)
        arbiter.add(self.cpu.dbus)

        # Connect up our CPU interrupt lines.
        m.d.comb += self.cpu.ip.eq(self.intc.ip)

        # If we're automatically creating a debug connection, do so.
        if self._auto_debug:
            m.d.comb += [
                self.cpu._cpu.jtag.tck  .eq(synchronize(m, platform.request("user_io", 0, dir="i"))),
                self.cpu._cpu.jtag.tms  .eq(synchronize(m, platform.request("user_io", 1, dir="i"))),
                self.cpu._cpu.jtag.tdi  .eq(synchronize(m, platform.request("user_io", 2, dir="i"))),
                platform.request("user_io", 3, dir="o")  .eq(self.cpu._cpu.jtag.tdo)
            ]

        return m



    def resources(self, omit_bios_mem=True):
        """ Creates an iterator over each of the device's addressable resources.

        Yields (resource, address, size) for each resource.

        Parameters:
            omit_bios_mem -- If True, BIOS-related memories are skipped when generating our
                             resource listings. This hides BIOS resources from the application.
        """

        # Grab the memory map for this SoC...
        memory_map = self.bus_decoder.bus.memory_map

        # ... find each addressable peripheral...
        for peripheral, (peripheral_start, _end, _granularity) in memory_map.windows():
            resources = peripheral.all_resources()

            # ... find the peripheral's resources...
            for resource, (register_offset, register_end_offset, _local_granularity) in resources:

                if self._build_bios and omit_bios_mem:
                    # If we're omitting bios resources, skip the BIOS ram/rom.
                    if (self.ram._mem is resource) or (self.rom._mem is resource):
                        continue

                # ... and extract the peripheral's range/vitals...
                size = register_end_offset - register_offset
                yield resource, peripheral_start + register_offset, size


    def build(self, name=None, build_dir="build"):
        """ Builds any internal artifacts necessary to create our CPU.

        This is usually used for e.g. building our BIOS.

        Parmeters:
            name      -- The name for the SoC design.
            build_dir -- The directory where our main nMigen build is being performed.
                         We'll build in a subdirectory of it.
        """

        # If we're building a BIOS, let our superclass build a BIOS for us.
        if self._build_bios:
            logging.info("Building SoC BIOS...")
            super().build(name=name, build_dir=os.path.join(build_dir, 'soc'), do_build=True, do_init=True)
            logging.info("BIOS build complete. Continuing with SoC build.")

        self.log_resources()


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
        emit(" *")
        emit(" * Automatically generated by LUNA; edits will be discarded on rebuild.")
        emit(" * (Most header files phrase this 'Do not edit.'; be warned accordingly.)")
        emit(" *")
        emit(f" * Generated: {datetime.datetime.now()}.")
        emit(" */")
        emit("")

        emit("MEMORY")
        emit("{")

        # Add regions for our main ROM and our main RAM.
        for memory in [self._main_rom, self._main_ram]:

            # Figure out our fields: a region name, our start, and our size.
            name = "ram" if (memory is self._main_ram) else "rom"
            start, size = self._range_for_peripheral(memory)

            if size:
                emit(f"    {name} : ORIGIN = 0x{start:08x}, LENGTH = {size:08x}")

        emit("}")
        emit("")


    def log_resources(self):
        """ Logs a summary of our resource utilization to our running logs. """

        # Resource addresses:
        logging.info("Physical address allocations:")
        for peripheral, (start, end, _granularity) in self.memory_map.all_resources():
            logging.info(f"    {start:08x}-{end:08x}: {peripheral}")
        logging.info("")

        # IRQ numbers
        logging.info("IRQ allocations:")
        for irq, peripheral in self._irqs.items():
            logging.info(f"    {irq}: {peripheral}")
        logging.info("")


        # Main memory.
        if self._build_bios:
            memory_location = self.main_ram_address()

            logging.info(f"Main memory at 0x{memory_location:08x}; upload using:")
            logging.info(f"    flterm --kernel <your_firmware> --kernel-addr 0x{memory_location:08x} --speed {self._uart_baud}")
            logging.info("or")
            logging.info(f"    lxterm --kernel <your_firmware> --kernel-adr 0x{memory_location:08x} --speed {self._uart_baud}")

        logging.info("")


    def main_ram_address(self):
        """ Returns the address of the main system RAM. """
        start, _  = self._range_for_peripheral(self._main_ram)
        return start
