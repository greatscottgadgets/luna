#!/usr/bin/env python3
#
# This file is part of LUNA.
#

import operator
from functools import reduce

from nmigen import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal, ResetInserter
from nmigen.lib.cdc import FFSynchronizer

from luna.gateware.platform        import get_appropriate_platform
from luna.gateware.interface.spi   import SPIRegisterInterface
from luna.gateware.interface.ulpi  import UMTITranslator
from luna.gateware.interface.flash import ECP5ConfigurationFlashInterface

REGISTER_ID             = 1
REGISTER_LEDS           = 2
REGISTER_TARGET_POWER   = 3

REGISTER_USER_IO_DIR    = 4
REGISTER_USER_IO_IN     = 5
REGISTER_USER_IO_OUT    = 6

REGISTER_TARGET_ADDR    = 7
REGISTER_TARGET_VALUE   = 8
REGISTER_TARGET_RXCMD   = 9

REGISTER_HOST_ADDR      = 10
REGISTER_HOST_VALUE     = 11
REGISTER_HOST_RXCMD     = 12

REGISTER_SIDEBAND_ADDR  = 13
REGISTER_SIDEBAND_VALUE = 14
REGISTER_SIDEBAND_RXCMD = 15

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

        10 -- host PHY ULPI register address
        11 -- host PHY ULPI register value
        12 -- last host PHY RxCmd

        13 -- sideband PHY ULPI register address
        14 -- sideband PHY ULPI register value
        15 -- last sideband PHY RxCmd
    """

    def elaborate(self, platform):
        m = Module()

        clk_60MHz = platform.request(platform.default_clk)

        # Drive the sync clock domain with our main clock.
        m.domains.sync = ClockDomain()
        m.d.comb += ClockSignal().eq(clk_60MHz)

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
        for i in range(4):
            pin = platform.request("user_io", i)
            m.d.comb += [
                pin.oe         .eq(user_io_ddr[i]),
                user_io_in[i]  .eq(pin.i),
                pin.o          .eq(user_io_out[i])
            ]


        #
        # ULPI PHY windows
        #
        self.add_ulpi_registers(m, platform,
            clock=clk_60MHz,
            ulpi_bus="target_phy",
            register_base=REGISTER_TARGET_ADDR
        )
        self.add_ulpi_registers(m, platform,
            clock=clk_60MHz,
            ulpi_bus="host_phy",
            register_base=REGISTER_HOST_ADDR
        )
        self.add_ulpi_registers(m, platform,
            clock=clk_60MHz,
            ulpi_bus="sideband_phy",
            register_base=REGISTER_SIDEBAND_ADDR
        )

        #
        # SPI flash passthrough connections.
        #
        flash_sdo = Signal()

        spi_flash_bus = platform.request('spi_flash')
        spi_flash_passthrough = ECP5ConfigurationFlashInterface(bus=spi_flash_bus)

        m.submodules += spi_flash_passthrough 
        m.d.comb += [
            spi_flash_passthrough.sck   .eq(board_spi.sck),
            spi_flash_passthrough.sdi   .eq(board_spi.sdi),
            flash_sdo                   .eq(spi_flash_passthrough.sdo),
        ]


        #
        # Structural connections.
        #
        sck = Signal()
        sdi = Signal()
        cs  = Signal()
        gateware_sdo = Signal()

        #
        # Synchronize each of our I/O SPI signals, where necessary.
        #
        m.submodules += FFSynchronizer(board_spi.sck, sck)
        m.submodules += FFSynchronizer(board_spi.sdi, sdi)
        m.submodules += FFSynchronizer(board_spi.cs,  cs)

        # Select the passthrough or gateware SPI based on our chip-select values.
        with m.If(spi_registers.cs):
            m.d.comb += board_spi.sdo.eq(gateware_sdo)
        with m.Else():
            m.d.comb += board_spi.sdo.eq(flash_sdo)

        # Connect our register interface to our board SPI.
        m.d.comb += [
            spi_registers.sck .eq(sck),
            spi_registers.sdi .eq(sdi),
            gateware_sdo      .eq(spi_registers.sdo),
            spi_registers.cs  .eq(cs)
        ]

        return m


    def add_ulpi_registers(self, m, platform, *, ulpi_bus, clock, register_base):
        """ Adds a set of ULPI registers to the active design. """

        target_ulpi    = platform.request(ulpi_bus)
        umti_adapter   = UMTITranslator(ulpi=target_ulpi, clock=clock)
        m.submodules  += umti_adapter

        # ULPI register window.
        spi_registers = m.submodules.spi_registers
        spi_registers.add_register(register_base + 0,
            write_strobe=umti_adapter.manual_read,
            value_signal=umti_adapter.address,
            size=6
        )
        spi_registers.add_sfr(register_base + 1,
            read=umti_adapter.read_data,
            write_signal=umti_adapter.write_data,
            write_strobe=umti_adapter.manual_write
        )
        spi_registers.add_sfr(register_base + 2,
            read=umti_adapter.last_rx_command
        )



if __name__ == "__main__":
    platform = get_appropriate_platform()
    platform.build(InteractiveSelftest(), do_program=True)
