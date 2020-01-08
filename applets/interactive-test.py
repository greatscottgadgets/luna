#!/usr/bin/env python3
#
# This file is part of LUNA.
#

from nmigen import Signal, Elaboratable, Module, Cat, ClockDomain, ClockSignal
from nmigen.lib.cdc import FFSynchronizer

from luna.gateware.platform import *
from luna.gateware.interface.spi import SPIRegisterInterface
from luna.gateware.interface.ulpi import ULPIRegisterWindow


class InteractiveSelftest(Elaboratable):
    """ Hardware meant to demonstrate use of the Debug Controller's register interface.
    
    Registers:
        0 -- register/address size auto-negotiation for Apollo
        1 -- gateware ID register (TEST)
        2 -- fpga LEDs
        3 -- target port power control


        7 -- target PHY ULPI register address
        8 -- target PHY ULPI register value
        9 -- target ULPI state
    """


    def elaborate(self, platform):
        m = Module()


        # Explicitly create our main clock domain.
        # This allows us to pass our clock e.g. to the ULPI PHYs.
        sync = ClockDomain()
        m.domains.sync = sync

        # Drive that clock domain with our main clock.
        clk_60MHz = platform.request(platform.default_clk)
        m.d.comb      += ClockSignal().eq(clk_60MHz)


        # Create a set of registers, and expose them over SPI.
        board_spi = platform.request("debug_spi")
        spi_registers = SPIRegisterInterface(default_read_value=-1)
        m.submodules.spi_registers = spi_registers

        # Simple applet ID register.
        spi_registers.add_read_only_register(1, read=0x54455354)

        # LED test register.
        led_reg = spi_registers.add_register(2, size=6, name="leds", reset=0b10)
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
        spi_registers.add_sfr(3, 
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
        # ULPI target PHY hardware
        #
        target_ulpi    = platform.request("target_phy")

        target_addr_change  = Signal()
        target_read_data    = Signal(8)

        target_address   = spi_registers.add_register(7, write_strobe=target_addr_change, size=6)
        spi_registers.add_sfr(8, read=target_read_data)

        ulpi_control = spi_registers.add_register(9, size=1)

        spi_registers.add_sfr(10, read=target_ulpi.data.i)

        # ULPI target PHY access.
        target_registers = ULPIRegisterWindow()
        m.submodules.target_phy = target_registers


        # Connect our register window and ULPI PHY.
        m.d.comb += [

            # Drive the bus whenever the target PHY isn't.
            target_ulpi.data.oe.eq(~target_ulpi.dir),

            # For now, keep the ULPI PHY out of reset and clocked.
            target_ulpi.clk               .eq(clk_60MHz),
            target_ulpi.reset             .eq(sync.rst),
            target_ulpi.data.o            .eq(target_registers.ulpi_data_out),

            #target_ulpi_busy              .eq(target_registers.busy),
            target_registers.address      .eq(target_address),
            target_registers.read_request .eq(target_addr_change),
            target_read_data              .eq(target_registers.read_data),

            target_registers.ulpi_data_in .eq(target_ulpi.data.i),
            target_registers.ulpi_dir     .eq(target_ulpi.dir),
            target_registers.ulpi_next    .eq(target_ulpi.nxt),

            target_ulpi.stp               .eq(target_registers.ulpi_stop),
        ]

        user_io = Cat([platform.request("user_io", i, dir="o") for i in range(4)])
        m.d.comb += user_io.eq(target_ulpi.data)


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
    platform = LUNAPlatformR01()
    platform.build(InteractiveSelftest(), do_program=True)
