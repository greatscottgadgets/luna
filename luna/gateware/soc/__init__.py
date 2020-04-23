#
# This file is part of LUNA.
#

from nmigen                  import Elaboratable, Module
from nmigen_soc              import wishbone

from lambdasoc.soc.cpu       import CPUSoC
from lambdasoc.cpu.minerva   import MinervaCPU
from lambdasoc.periph.intc   import GenericInterruptController
from lambdasoc.periph.serial import AsyncSerialPeripheral
from lambdasoc.periph.sram   import SRAMPeripheral
from lambdasoc.periph.timer  import TimerPeripheral

from .memory                 import WishboneROM


class SimpleSoC(CPUSoC, Elaboratable):
    """ Class used for building simple, example system-on-a-chip architectures.

    Intended to facilitate demonstrations (and very simple USB devices) by providing
    a wrapper that can be updated as the nMigen-based-SoC landscape changes. Hopefully,
    this will eventually be filled by e.g. nMigen-compatible-LiteX. :)

    SimpleSoC devices are guaranteed to intergrate:
        - A simple riscv32i processor.
        - One or more read-only or read-write memories.
        - A number of nmigen-soc peripherals.

    The current implementation uses a single, 32-bit wide Wishbone bus
    as the system's backend.
    """

    BUS_ADDRESS_WIDTH = 30

    def __init__(self):
        self.peripherals = []
        self.submodules  = []

    def add_firmware_rom(self, firmware_filename, addr=0):
        """ Reads the firmware from the provided filename; and creates a ROM with its contents.

        Parameters:
            filename -- The filename that contains the RISC-V firmware to be loaded.
            addr     -- The address at which the ROM should reside.
        """
        with open(firmware_filename, "rb") as f:
            data = f.read()
            return self.add_rom(data, addr=addr)


    def add_rom(self, data, addr=0):
        """ Creates a simple ROM and adds it to the design.

        Parameters:
            data -- The data to fill the relevant ROM.
            addr -- The address at which the ROM should reside.
            """
        rom = WishboneROM(data)
        return self.add_peripheral(rom, addr=addr)


    def add_ram(self, size: int, addr: int):
        """ Creates a simple RAM and adds it to our design.

        Parameters:
            size -- The size of the RAM, in bytes. Will be rounded to the nearest power of two.
            addr -- The address at which to place the RAM.
        """

        # ... and add it as a peripheral.
        ram = SRAMPeripheral(size=size)
        return self.add_peripheral(ram, addr=addr)


    def add_peripheral(self, p, **kwargs):
        """ Adds a peripheral to the SoC.

        For now, this is identical to adding a peripheral to the SoC's wishbone bus.
        For convenience, returns the peripheral provided.
        """

        self.peripherals.append((p, kwargs,))
        return p


    def elaborate(self, platform):
        m = Module()

        next_irq_index = 0

        # Add our core CPU, and create its main system bus.
        # Note that our default implementation uses a single bus for code and data,
        # so this is both the instruction bus (ibus) and data bus (dbus).
        m.submodules.cpu = cpu = MinervaCPU()
        m.submodules.bus = bus = wishbone.Decoder(addr_width=30, data_width=32, granularity=8, features={"cti", "bte"})

        # Create a basic programmable interrupt controller for our CPU.
        m.submodules.pic = pic = GenericInterruptController(width=len(cpu.ip))

        # Add each of our peripherals to the bus.
        for peripheral, parameters in self.peripherals:

            # Add the peripheral to our bus...
            interface = getattr(peripheral, 'bus')
            bus.add(interface, **parameters)

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
