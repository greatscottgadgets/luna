#
# This file is part of LUNA.
#

from nmigen     import Elaboratable, Module
from nmigen_soc import wishbone

from .cpu       import Processor
from .memory    import WishboneRAM, WishboneROM


class SimpleSoC(Elaboratable):
    """ Class used for building simple system-on-a-chip architectures.

    Intended to facilitate demonstrations and simple USB devices.

    SimpleSoC devices integrate:
        - A simple riscv32i processor.
        - One or more read-only or re-write memories.
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


    def add_peripheral(self, p, **kwargs):
        """ Adds a peripheral to the SoC.

        For now, this is identical to adding a peripheral to the SoC's wishbone bus.
        For convenience, returns the peripheral provided.
        """

        self.peripherals.append((p, kwargs,))
        return p


    def elaborate(self, platform):
        m = Module()

        # Add our core CPU, and create its main system bus.
        # Note that our default implementation uses a single bus for code and data,
        # so this is both the instruction bus (ibus) and data bus (dbus).
        m.submodules.cpu = cpu = Processor()
        m.submodules.bus = bus = wishbone.Decoder(addr_width=30, data_width=32, granularity=8)

        # Add each of our peripherals to the bus.
        for peripheral, parameters in self.peripherals:

            # Add the peripheral to our bus...
            interface = getattr(peripheral, 'bus')
            bus.add(interface, **parameters)

            # ... and include it in the processor.
            m.submodules += peripheral

        # Merge the CPU's data and instruction busses. This essentially means taking the two
        # separate bus masters (the CPU ibus master and the CPU dbus master), and connecting them
        # to an arbiter, so they both share use of the single bus.

        # Create the arbiter around our main bus...
        m.submodules.bus_arbiter = arbiter = wishbone.Arbiter(addr_width=30, data_width=32, granularity=8)
        m.d.comb += arbiter.bus.connect(bus.bus)

        # ... and connect it to the CPU instruction and data busses.
        arbiter.add(cpu.ibus)
        arbiter.add(cpu.dbus)

        return m
