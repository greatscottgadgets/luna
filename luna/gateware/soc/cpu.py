#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from minerva.core import Minerva
from amaranth_soc   import wishbone

class Processor(Minerva):
    """ Compatibility subclass around the Minerva RISC-V (riscv32i) processor. """

    # List of features supported by the Minerva processor's wishbone busses.
    MINERVA_BUS_FEATURES = {'cti', 'bte', 'err'}

    def __init__(self, *args, **kwargs):

        # Create the basic Minerva processor...
        super().__init__(*args, **kwargs)

        # ... and replace its Record-based busses with amaranth-soc ones.
        self.ibus = wishbone.Interface(addr_width=30, data_width=32, features=self.MINERVA_BUS_FEATURES)
        self.dbus = wishbone.Interface(addr_width=30, data_width=32, features=self.MINERVA_BUS_FEATURES)
