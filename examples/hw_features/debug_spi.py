#
# This file is part of LUNA.
#

from nmigen import *
from luna.gateware.platform import *
from luna.gateware.interface.spi import SPICommandInterface


class DebugSPIExample(Elaboratable):
    """ Hardware meant to demonstrate use of the Debug Controller's SPI interface. """


    def __init__(self):

        # Base ourselves around an SPI command interface.
        self.interface = SPICommandInterface()


    def elaborate(self, platform):
        m = Module()

        # Use our command interface.
        m.submodules.interface = self.interface

        # Connect our command interface to our board SPI.
        board_spi = platform.request("debug_spi")
        m.d.comb += [
            self.interface.sck.eq(board_spi.sck),
            self.interface.sdi.eq(board_spi.sdi),
            board_spi.sdo.eq(self.interface.sdo)
        ]

        # Turn on a single LED, just to show something's running.
        led = platform.request('led', 0)
        m.d.comb += led.eq(1)

        # Mirror each of the SPI signals on the User I/O header for observability.
        user_io = [platform.request("user_io", i, dir="o") for i in range(0, 4)]
        m.d.comb += [
            user_io[0].eq(board_spi.sck),
            user_io[1].eq(board_spi.sdi),
            user_io[2].eq(self.interface.sdo),
            user_io[3].eq(board_spi.sdi)
        ]

        # For now, always respond with a constant.
        m.d.comb += self.interface.word_to_output.eq(0xDEADBEEF)

        return m


if __name__ == "__main__":
    platform = LUNAPlatformR01()
    platform.build(DebugSPIExample(), do_program=True)
