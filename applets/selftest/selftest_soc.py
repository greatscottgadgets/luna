#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth                      import *
from amaranth.hdl.xfrm             import DomainRenamer

from lambdasoc.periph              import Peripheral
from lambdasoc.periph.timer        import TimerPeripheral

from luna                          import top_level_cli
from luna.gateware.soc             import SimpleSoC, UARTPeripheral
from luna.gateware.interface.ulpi  import ULPIRegisterWindow
from luna.gateware.interface.psram import HyperRAMInterface


# Run our tests at a slower clock rate, for now.
# TODO: bump up the fast clock rate, to test the HyperRAM at speed?
CLOCK_FREQUENCIES_MHZ = {
    "fast": 120,
    "sync":  60,
    "usb":   60
}


class LEDPeripheral(Peripheral, Elaboratable):
    """ Simple peripheral that controls the board's LEDs. """

    def __init__(self, name="leds"):
        super().__init__(name=name)

        # Create our LED register.
        bank            = self.csr_bank()
        self._output    = bank.csr(6, "rw")

        # ... and convert our register into a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus


    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        # Grab our LEDS...
        leds = Cat(platform.request("led", i) for i in range(6))

        # ... and update them on each register write.
        with m.If(self._output.w_stb):
            m.d.sync += [
                self._output.r_data  .eq(self._output.w_data),
                leds                 .eq(self._output.w_data),
            ]

        return m



class ULPIRegisterPeripheral(Peripheral, Elaboratable):
    """ Peripheral that provides access to a ULPI PHY, and its registers. """

    def __init__(self, name="ulpi", io_resource_name="usb"):
        super().__init__(name=name)
        self._io_resource = io_resource_name

        # Create our registers...
        bank            = self.csr_bank()
        self._address   = bank.csr(8, "w")
        self._value     = bank.csr(8, "rw")
        self._busy      = bank.csr(1, "r")

        # ... and convert our register into a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus


    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        # Grab a connection to our ULPI PHY.
        target_ulpi = platform.request(self._io_resource)

        #
        # ULPI Register Window
        #
        ulpi_reg_window  = ULPIRegisterWindow()
        m.submodules  += ulpi_reg_window

        # Connect up the window.
        m.d.comb += [
            ulpi_reg_window.ulpi_data_in  .eq(target_ulpi.data.i),
            ulpi_reg_window.ulpi_dir      .eq(target_ulpi.dir.i),
            ulpi_reg_window.ulpi_next     .eq(target_ulpi.nxt.i),

            target_ulpi.clk               .eq(ClockSignal("usb")),
            target_ulpi.rst               .eq(ResetSignal("usb")),
            target_ulpi.stp               .eq(ulpi_reg_window.ulpi_stop),
            target_ulpi.data.o            .eq(ulpi_reg_window.ulpi_data_out),
            target_ulpi.data.oe           .eq(~target_ulpi.dir.i)
        ]

        #
        # Address register logic.
        #

        # Perform a read request whenever the user writes to ULPI address...
        m.d.sync += ulpi_reg_window.read_request.eq(self._address.w_stb)

        # And update the register address accordingly.
        with m.If(self._address.w_stb):
            m.d.sync += ulpi_reg_window.address.eq(self._address.w_data)


        #
        # Value register logic.
        #

        # Always report back the last read data.
        m.d.comb += self._value.r_data.eq(ulpi_reg_window.read_data)

        # Perform a write whenever the user writes to our ULPI value.
        m.d.sync += ulpi_reg_window.write_request.eq(self._value.w_stb)
        with m.If(self._address.w_stb):
            m.d.sync += ulpi_reg_window.write_data.eq(self._value.w_data)


        #
        # Busy register logic.
        #
        m.d.comb += self._busy.r_data.eq(ulpi_reg_window.busy)

        return m


class PSRAMRegisterPeripheral(Peripheral, Elaboratable):
    """ Peripheral that provides access to a ULPI PHY, and its registers. """

    def __init__(self, name="ram"):
        super().__init__(name=name)

        # Create our registers...
        bank            = self.csr_bank()
        self._address   = bank.csr(32, "w")
        self._value     = bank.csr(32, "r")
        self._busy      = bank.csr(1,  "r")

        # ... and convert our register into a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus


    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        #
        # HyperRAM interface window.
        #
        ram_bus = platform.request('ram')
        m.submodules.psram = psram = HyperRAMInterface(bus=ram_bus, clock_skew=platform.ram_timings['clock_skew'])

        # Hook up our PSRAM.
        m.d.comb += [
            ram_bus.reset          .eq(0),
            psram.single_page      .eq(0),
            psram.perform_write    .eq(0),
            psram.register_space   .eq(1),
            psram.final_word       .eq(1),
        ]

        #
        # Address register logic.
        #

        # Perform a read request whenever the user writes the address register...
        m.d.sync += psram.start_transfer.eq(self._address.w_stb)

        # And update the register address accordingly.
        with m.If(self._address.w_stb):
            m.d.sync += psram.address.eq(self._address.w_data)


        #
        # Value register logic.
        #

        # Always report back the last read data.
        with m.If(psram.new_data_ready):
            m.d.sync += self._value.r_data.eq(psram.read_data)


        #
        # Busy register logic.
        #
        m.d.comb += self._busy.r_data.eq(~psram.idle)

        return m



class SelftestCore(Elaboratable):
    """ Simple soft-core that executes the LUNA factory tests. """

    def __init__(self):
        clock_freq = 60e6

        # Create our SoC...
        self.soc = soc = SimpleSoC()

        # ... add a ROM for firmware...
        soc.add_rom('selftest.bin', size=0x4000)

        # ... and a RAM for execution.
        soc.add_ram(0x4000)

        # ...  add our UART peripheral...
        self.uart = uart = UARTPeripheral(divisor=int(clock_freq // 115200))
        soc.add_peripheral(uart)

        # ... add a timer, so our software can get precise timing.
        self.timer = TimerPeripheral(32)
        soc.add_peripheral(self.timer)

        # ... and add our peripherals under test.
        peripherals = (
            LEDPeripheral(name="leds"),
            ULPIRegisterPeripheral(name="target_ulpi",   io_resource_name="target_phy"),
            ULPIRegisterPeripheral(name="host_ulpi",     io_resource_name="host_phy"),
            ULPIRegisterPeripheral(name="sideband_ulpi", io_resource_name="sideband_phy"),
            PSRAMRegisterPeripheral(name="psram"),
        )

        for peripheral in peripherals:
            soc.add_peripheral(peripheral)



    def elaborate(self, platform):
        m = Module()

        m.submodules.car = platform.clock_domain_generator(clock_frequencies=CLOCK_FREQUENCIES_MHZ)

        # Add our SoC to the design...
        m.submodules.soc = self.soc

        # ... and connect up its UART.
        uart_io  = platform.request("uart", 0)
        m.d.comb += [
            uart_io.tx         .eq(self.uart.tx),
            self.uart.rx       .eq(uart_io.rx),
        ]

        if hasattr(uart_io.tx, 'oe'):
            m.d.comb += uart_io.tx.oe.eq(self.uart.driving & self.uart.enabled),

        return m


if __name__ == "__main__":
    design = SelftestCore()
    top_level_cli(design, cli_soc=design.soc)
