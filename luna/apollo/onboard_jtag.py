#
# This file is part of LUNA
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" JTAG definitions for on-board JTAG devices. """

from .jtag import JTAGDevice


#
# ECP5 FPGAs that can be populated onto LUNA boards.
#

class LatticeECP5_12F(JTAGDevice):
    DEVICE = 'LFE5U-12F'
    DESCRIPTION = "Lattice LFE5U-12F ECP5 FPGA"
    SUPPORTED_IDCODES = [0x21111043]

class LatticeECP5_25F(JTAGDevice):
    DEVICE = 'LFE5U-25F'
    DESCRIPTION = "Lattice LFE5U-25F ECP5 FPGA"
    SUPPORTED_IDCODES = [0x41111043]

class LatticeECP5_45F(JTAGDevice):
    DEVICE = 'LFE5U-45F'
    DESCRIPTION = "Lattice LFE5U-45F ECP5 FPGA"
    SUPPORTED_IDCODES = [0x41112043]

class LatticeECP5_85F(JTAGDevice):
    DEVICE = 'LFE5U-85F'
    DESCRIPTION = "Lattice LFE5U-85F ECP5 FPGA"
    SUPPORTED_IDCODES = [0x41113043]


#
# Daisho boards.
#

class IntelCycloneIV_EP4CE30(JTAGDevice):
    """ Class representing a JTAG-connected CycloneIV, as on Daisho. """

    DEVICE      = "EP4CE30"
    DESCRIPTION = "Intel/Altera EP4CE30 Cyclone-IV FPGA"
    SUPPORTED_IDCODES = [0x020f40dd]
