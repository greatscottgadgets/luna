#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import sys

from nmigen import Elaboratable, Module, Signal, Cat, Array
from nmigen.build import Pins, Attrs
from nmigen_boards.resources import SwitchResources, LEDResources

from luna import top_level_cli

# 1bitsquared dip switch pmod (https://1bitsquared.com/collections/fpga/products/pmod-dip-switch) in PMOD A
_dipswitch_pmod = [
    *SwitchResources("dipswitch", pins="pmod_0:1 pmod_0:2 pmod_0:3 pmod_0:4 pmod_0:7 pmod_0:8 pmod_0:9 pmod_0:10", attrs=Attrs(IO_TYPE="LVCMOS33")),
]

# 1bitsquared pmod 7 segment (https://1bitsquared.com/collections/fpga/products/pmod-7-segment-display) in PMOD B
_7seg_pmod = [
    *LEDResources("sevenseg_segments", pins="pmod_1:1 pmod_1:2 pmod_1:3 pmod_1:4 pmod_1:7 pmod_1:8 pmod_1:9", attrs=Attrs(IO_TYPE="LVCMOS33"), invert=True),
    *LEDResources("sevenseg_digit_select", pins="pmod_1:10", attrs=Attrs(IO_TYPE="LVCMOS33")),
]

_segment_lookup = Array([0b0111111,
                         0b0000110,
                         0b1011011,
                         0b1001111,
                         0b1100110,
                         0b1101101,
                         0b1111101,
                         0b0000111,
                         0b1111111,
                         0b1101111,
                         0b1110111,
                         0b1111100,
                         0b0111001,
                         0b1011110,
                         0b1111001,
                         0b1110001])

class Pmod(Elaboratable):
    """ Hardware module that validates basic LUNA pmod functionality. """


    def elaborate(self, platform):
        """ Generate the Pmod tester. """

        platform.add_resources(_dipswitch_pmod)
        platform.add_resources(_7seg_pmod)

        m = Module()

        input_lsb = [platform.request("dipswitch", ix).i for ix in range(0, 4)]
        input_msb = [platform.request("dipswitch", ix).i for ix in range(4, 8)]
        output_segments = [platform.request("sevenseg_segments", ix).o for ix in range(0, 7)]
        output_digit_select = platform.request("sevenseg_digit_select").o

        # Clock divider / counter.
        counter = Signal(28)

        # Sum two dipswitch sets
        dipswitch_sum = Signal(5)
        dipswitch_sum_bcd_lsb = Signal(4)
        dipswitch_sum_bcd_msb = Signal(4)
        
        m.d.sync += dipswitch_sum.eq(Cat(input_lsb) + Cat(input_msb))
        m.d.sync += dipswitch_sum_bcd_lsb.eq(dipswitch_sum % 10)
        with m.If(dipswitch_sum > 29):
            m.d.sync += dipswitch_sum_bcd_msb.eq(3)
        with m.Elif(dipswitch_sum > 19):
            m.d.sync += dipswitch_sum_bcd_msb.eq(2)
        with m.Elif(dipswitch_sum > 9):
            m.d.sync += dipswitch_sum_bcd_msb.eq(1)
        with m.Else():
            m.d.sync += dipswitch_sum_bcd_msb.eq(0)

        # mux digits
        with m.If(counter[10]):
            m.d.sync += output_digit_select.eq(~output_digit_select)
            m.d.sync += counter.eq(0)
            with m.If(output_digit_select):
                # msb digit
                m.d.sync += Cat(output_segments).eq(_segment_lookup[dipswitch_sum_bcd_msb])
            with m.Else():
                # lsb digit
                m.d.sync += Cat(output_segments).eq(_segment_lookup[dipswitch_sum_bcd_lsb])
        with m.Else():
            m.d.sync += counter.eq(counter+1)
        
        # Return our elaborated module.
        return m


if __name__ == "__main__":
    top_level_cli(Pmod)
