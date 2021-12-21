#!/usr/bin/env python3
# pylint: disable=maybe-no-member
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import sys
import time

from prompt_toolkit import HTML
from prompt_toolkit import print_formatted_text as pprint

from amaranth import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from amaranth.lib.cdc import FFSynchronizer

from luna                             import top_level_cli

from apollo_fpga                           import ApolloDebugger, ApolloILAFrontend
from luna.gateware.debug.ila          import SyncSerialILA


from luna.gateware.utils.cdc          import synchronize
from luna.gateware.architecture.car   import LunaECP5DomainGenerator
from luna.gateware.interface.spi      import SPIRegisterInterface, SPIMultiplexer, SPIBus
from luna.gateware.interface.ulpi     import UTMITranslator
from luna.gateware.usb.analyzer       import USBAnalyzer


DATA_AVAILABLE  = 1
ANALYZER_RESULT = 2


class ULPIDiagnostic(Elaboratable):
    """ Gateware that evalutes ULPI PHY functionality. """


    def elaborate(self, platform):
        m = Module()

        # Generate our clock domains.
        clocking = LunaECP5DomainGenerator()
        m.submodules.clocking = clocking

        # Grab a reference to our debug-SPI bus.
        board_spi = synchronize(m, platform.request("debug_spi").i)

        # Create our SPI-connected registers.
        m.submodules.spi_registers = spi_registers = SPIRegisterInterface(7, 8)
        m.d.comb += spi_registers.spi.connect(board_spi)

        # Create our UTMI translator.
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.utmi = utmi = UTMITranslator(ulpi=ulpi)


        # Strap our power controls to be in VBUS passthrough by default,
        # on the target port.
        m.d.comb += [
            platform.request("power_a_port").o      .eq(0),
            platform.request("pass_through_vbus").o .eq(1),
        ]


        # Hook up our LEDs to status signals.
        m.d.comb += [
            platform.request("led", 2).o  .eq(utmi.session_valid),
            platform.request("led", 3).o  .eq(utmi.rx_active),
            platform.request("led", 4).o  .eq(utmi.rx_error)
        ]

        # Set up our parameters.
        m.d.comb += [

            # Set our mode to non-driving and full speed.
            utmi.op_mode     .eq(0b01),
            utmi.xcvr_select .eq(0b01),

            # Disable the DP/DM pull resistors.
            utmi.dm_pulldown .eq(0),
            utmi.dm_pulldown .eq(0),
            utmi.term_select .eq(0)
        ]

        read_strobe = Signal()

        # Create a USB analyzer, and connect a register up to its output.
        m.submodules.analyzer = analyzer = USBAnalyzer(utmi_interface=utmi)

        # Provide registers that indicate when there's data ready, and what the result is.
        spi_registers.add_read_only_register(DATA_AVAILABLE,  read=analyzer.data_available)
        spi_registers.add_read_only_register(ANALYZER_RESULT, read=analyzer.data_out, read_strobe=read_strobe)

        m.d.comb += [
            platform.request("led", 0).o  .eq(analyzer.capturing),
            platform.request("led", 1).o  .eq(analyzer.data_available),
            platform.request("led", 5).o  .eq(analyzer.overrun),

            analyzer.next               .eq(read_strobe)
        ]


        # Debug output.
        m.d.comb += [
            platform.request("user_io", 0, dir="o") .eq(ClockSignal("usb")),
            platform.request("user_io", 1, dir="o") .eq(ulpi.dir),
            platform.request("user_io", 2, dir="o") .eq(ulpi.nxt),
            platform.request("user_io", 3, dir="o") .eq(analyzer.sampling),
        ]


        # Return our elaborated module.
        return m


if __name__ == "__main__":
    analyzer = top_level_cli(ULPIDiagnostic)
    debugger = ApolloDebugger()

    time.sleep(1)

    def data_is_available():
        return debugger.spi.register_read(DATA_AVAILABLE)

    def read_byte():
        return debugger.spi.register_read(ANALYZER_RESULT)

    def get_next_byte():
        while not data_is_available():
            time.sleep(0.1)

        return read_byte()

    # Tiny stateful parser for our analyzer.
    while True:

        # Grab our header, and process it.
        size = (get_next_byte() << 16) | get_next_byte()

        # Then read and print out our body
        packet = [get_next_byte() for _ in range(size)]
        packet_hex = [f"{byte:02x}" for byte in packet]
        packet_as_string = bytes(packet)
        print(f"{packet_as_string}: {packet_hex}")

        #byte = get_next_byte()
        #print(f"{byte:02x} ", end="")
        #sys.stdout.flush()



