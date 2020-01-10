#!/usr/bin/env python3
#
# This file is part of LUNA.
#

import operator
from functools import reduce

from nmigen import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from nmigen.lib.cdc import FFSynchronizer

from luna.gateware.platform import get_appropriate_platform
from luna.gateware.interface.spi import SPIRegisterInterface
from luna.gateware.interface.ulpi import PHYResetController, ULPIRegisterWindow, ULPIRxEventDecoder

REGISTER_ID            = 1
REGISTER_LEDS          = 2
REGISTER_TARGET_POWER  = 3

REGISTER_USER_IO_DIR   = 4
REGISTER_USER_IO_IN    = 5
REGISTER_USER_IO_OUT   = 6

REGISTER_TARGET_ADDR   = 7
REGISTER_TARGET_VALUE  = 8
REGISTER_TARGET_RXCMD  = 9


class InteractiveSelftest(Elaboratable):
    """ Hardware meant to demonstrate use of the Debug Controller's register interface.
    
    Registers:
        0 -- register/address size auto-negotiation for Apollo
        1 -- gateware ID register (TEST)
        2 -- fpga LEDs
        3 -- target port power control

        4 -- user I/O DDR (1 = out, 0 = in)
        5 -- user I/O input state
        6 -- user I/O output values (used when DDR = 1)

        7 -- target PHY ULPI register address
        8 -- target PHY ULPI register value
        9 -- last target PHY RxCmd
    """


    def elaborate(self, platform):
        m = Module()

        clk_60MHz = platform.request(platform.default_clk)

        # Drive the sync clock domain with our main clock.
        m.domains.sync = ClockDomain()
        m.d.comb += ClockSignal().eq(clk_60MHz)

        # Generate a post-configuration / power-on reset for the USB PHYs.
        phy_power_on_reset = Signal()
        phy_defer_startup  = Signal()
        m.submodules.por   = PHYResetController()
        m.d.comb +=  [ 
            phy_power_on_reset .eq(m.submodules.por.phy_reset),
            phy_defer_startup  .eq(m.submodules.por.phy_stop)
        ]

        # Create a set of registers, and expose them over SPI.
        board_spi = platform.request("debug_spi")
        spi_registers = SPIRegisterInterface(default_read_value=-1)
        m.submodules.spi_registers = spi_registers

        # Simple applet ID register.
        spi_registers.add_read_only_register(REGISTER_ID, read=0x54455354)

        # LED test register.
        led_reg = spi_registers.add_register(REGISTER_LEDS, size=6, name="leds", reset=0b10)
        led_out   = Cat([platform.request("led", i, dir="o") for i in range(0, 6)])
        m.d.comb += led_out.eq(led_reg)

        #
        # Target power test register.
        # Note: these values assume you've populated the correct AP22814 for
        #       your revision (AP22814As for rev0.2+, and AP22814Bs for rev0.1).
        #     bits [1:0]: 0 = power off
        #                 1 = provide A-port VBUS
        #                 2 = pass through target VBUS
        #
        power_test_reg          = Signal(3)
        power_test_write_strobe = Signal()
        power_test_write_value  = Signal(2)
        spi_registers.add_sfr(REGISTER_TARGET_POWER, 
            read=power_test_reg, 
            write_strobe=power_test_write_strobe, 
            write_signal=power_test_write_value
        )

        # Store the values for our enable bits.
        with m.If(power_test_write_strobe):
            m.d.sync += power_test_reg[0:2].eq(power_test_write_value)

        # Decode the enable bits and control the two power supplies.
        power_a_port      = platform.request("power_a_port")
        power_passthrough = platform.request("pass_through_vbus")
        with m.If(power_test_reg[0:2] == 1):
            m.d.comb += [
                power_a_port       .eq(1),
                power_passthrough  .eq(0)
            ]
        with m.Elif(power_test_reg[0:2] == 2):
            m.d.comb += [
                power_a_port       .eq(0),
                power_passthrough  .eq(1)
            ]
        with m.Else():
            m.d.comb += [
                power_a_port       .eq(0),
                power_passthrough  .eq(0)
            ]

        #
        # User IO GPIO registers.
        #

        # Data direction register.
        user_io_ddr = spi_registers.add_register(REGISTER_USER_IO_DIR, size=4)

        # Pin (input) state register.
        user_io_in  = Signal(4)
        spi_registers.add_sfr(REGISTER_USER_IO_IN, read=user_io_in)

        # Output value register.
        user_io_out = spi_registers.add_register(REGISTER_USER_IO_OUT, size=4)

        # Grab and connect each of our user-I/O ports our GPIO registers.
        #for i in range(4):
            #pin = platform.request("user_io", i)
            #m.d.comb += [
                #pin.oe         .eq(user_io_ddr[i]),
                #user_io_in[i]  .eq(pin.i),
                #pin.o          .eq(user_io_out[i])
            #]


        #
        # ULPI target PHY hardware
        #
        target_ulpi    = platform.request("target_phy")

        # Target PHY register access.
        target_registers = ULPIRegisterWindow()
        m.submodules.target_phy = target_registers

        # Target PHY RxCmd decoder.
        target_rxcmd_decoder = ULPIRxEventDecoder()
        m.submodules.target_rxcmd = target_rxcmd_decoder

        target_addr_change  = Signal()
        target_read_data    = Signal(8)

        # ULPI register window.
        target_address   = spi_registers.add_register(REGISTER_TARGET_ADDR, write_strobe=target_addr_change, size=6)
        spi_registers.add_sfr(REGISTER_TARGET_VALUE, read=target_read_data)
        spi_registers.add_sfr(REGISTER_TARGET_RXCMD, read=target_rxcmd_decoder.last_rx_command)

        # Connect our RxCmd decoder.
        m.d.comb += [
            target_rxcmd_decoder.ulpi_data_in .eq(target_ulpi.data.i),
            target_rxcmd_decoder.ulpi_dir     .eq(target_ulpi.dir),
            target_rxcmd_decoder.ulpi_next    .eq(target_ulpi.nxt),
        ]

        # Connect our register window and ULPI PHY.
        m.d.comb += [

            # Drive the bus whenever the target PHY isn't.
            target_ulpi.data.oe.eq(~target_ulpi.dir),

            # For now, keep the ULPI PHY out of reset and clocked.
            target_ulpi.clk               .eq(clk_60MHz),
            target_ulpi.reset             .eq(phy_power_on_reset),
            target_ulpi.data.o            .eq(target_registers.ulpi_data_out),

            #target_ulpi_busy              .eq(target_registers.busy),
            target_registers.address      .eq(target_address),
            target_registers.read_request .eq(target_addr_change),
            target_read_data              .eq(target_registers.read_data),

            target_registers.ulpi_data_in .eq(target_ulpi.data.i),
            target_registers.ulpi_dir     .eq(target_ulpi.dir),
            target_registers.ulpi_next    .eq(target_ulpi.nxt),

            target_ulpi.stp               .eq(phy_defer_startup)
        ]

        # Debug output.
        user_io = Cat([platform.request("user_io", i, dir="o") for i in range(4)])
        m.d.comb += [
            user_io[0].eq(target_ulpi.reset),
            user_io[1].eq(target_ulpi.stp),
            user_io[2].eq(target_ulpi.nxt),
            user_io[3].eq(target_ulpi.dir)
        ]

        #
        # Structural connections.
        #
        sck = Signal()
        sdi = Signal()
        sdo = Signal()
        cs  = Signal()

        #
        # Synchronize each of our I/O SPI signals, where necessary.
        #
        m.submodules += FFSynchronizer(board_spi.sck, sck)
        m.submodules += FFSynchronizer(board_spi.sdi, sdi)
        m.submodules += FFSynchronizer(board_spi.cs,  cs)
        m.d.comb     += board_spi.sdo.eq(sdo)

        # Connect our register interface to our board SPI.
        m.d.comb += [
            spi_registers.sck.eq(sck),
            spi_registers.sdi.eq(sdi),
            sdo.eq(spi_registers.sdo),
            spi_registers.cs .eq(cs)
        ]

        return m


if __name__ == "__main__":
    platform = get_appropriate_platform()
    platform.build(InteractiveSelftest(), do_program=True)
