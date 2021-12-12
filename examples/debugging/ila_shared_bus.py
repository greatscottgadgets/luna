#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

# NOTE: This example requires a working `gtkwave` binary
# to be present and on the system path; and will display the
# relevant output automatically in GTKWave.

import time

from amaranth import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from amaranth.lib.cdc import FFSynchronizer

from luna                          import top_level_cli
from apollo_fpga                        import ApolloDebugger, ApolloILAFrontend
from luna.gateware.utils.cdc       import synchronize
from luna.gateware.interface.spi   import SPIRegisterInterface, SPIMultiplexer, SPIBus
from luna.gateware.debug.ila       import SyncSerialILA

REGISTER_ID  = 1
REGISTER_ILA = 2

class ILASharedBusExample(Elaboratable):
    """
    Gateware that demonstrates sharing the Debug SPI bus between
    a register interface and an ILA.
    """

    def __init__(self):
        self.counter = Signal(28)
        self.toggle  = Signal()
        self.ila  = SyncSerialILA(signals=[self.counter, self.toggle], sample_depth=32)


    def elaborate(self, platform):
        m = Module()
        m.submodules += self.ila

        # Grab a reference to our debug-SPI bus.
        board_spi = synchronize(m, platform.request("debug_spi"))

        # Clock divider / counter.
        m.d.sync += self.counter.eq(self.counter + 1)

        # Another example signal, for variety.
        m.d.sync += self.toggle.eq(~self.toggle)

        # Create an SPI bus for our ILA.
        ila_spi = SPIBus()
        m.d.comb += [
            self.ila.spi .connect(ila_spi),

            # For sharing, we'll connect the _inverse_ of the primary
            # chip select to our ILA bus. This will allow us to send
            # ILA data when CS is un-asserted, and register data when
            # CS is asserted.
            ila_spi.cs  .eq(~board_spi.cs)
        ]

        # Create a set of registers...
        spi_registers = SPIRegisterInterface()
        m.submodules.spi_registers = spi_registers

        # ... and an SPI bus for them.
        reg_spi = SPIBus()
        m.d.comb += [
            spi_registers.spi .connect(reg_spi),
            reg_spi.cs        .eq(board_spi.cs)
        ]

        # Multiplex our ILA and register SPI busses.
        m.submodules.mux = SPIMultiplexer([ila_spi, reg_spi])
        m.d.comb += m.submodules.mux.shared_lines.connect(board_spi)

        # Add a simple ID register to demonstrate our registers.
        spi_registers.add_read_only_register(REGISTER_ID, read=0xDEADBEEF)

        # Create a simple SFR that will trigger an ILA capture when written,
        # and which will display our sample status read.
        spi_registers.add_sfr(REGISTER_ILA,
            read=self.ila.complete,
            write_strobe=self.ila.trigger
        )

        # Attach the LEDs and User I/O to the MSBs of our counter.
        leds    = [platform.request("led", i, dir="o") for i in range(0, 6)]
        m.d.comb += Cat(leds).eq(self.counter[-7:-1])

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    example = top_level_cli(ILASharedBusExample)

    # Create a debug and ILA connection.
    debugger = ApolloDebugger()
    ila      = ApolloILAFrontend(debugger, ila=example.ila, use_inverted_cs=True)

    # Trigger an ILA capture.
    debugger.spi.register_write(REGISTER_ILA, 0)

    # Wait for the capture to be complete.
    while not debugger.spi.register_read(REGISTER_ILA):
        time.sleep(0.001)

    # Finally, read back the capture and display it on-screen.
    ila.interactive_display()
