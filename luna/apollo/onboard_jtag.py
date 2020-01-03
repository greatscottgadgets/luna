#
# This file is part of LUNA
#
""" JTAG definitions for on-board JTAG devices. """

from .jtag import JTAGDevice


class LatticeECP5_12F(JTAGDevice):
    """ Class representing a JTAG-connected ECP5. """

    DESCRIPTION = "Lattice LFE5U-12F ECP5 FPGA"

    # A list of supported IDCODEs for the relevant class.
    # Used unless the supports_idcode() method is overridden.
    SUPPORTED_IDCODES = [0x21111043]
