#
# This file is part of LUNA.
#
# Copyright (c) 2025 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Core stream definitions for supporting native Amaranth 0.5 streams. """

from amaranth      import *
from amaranth.lib  import data

class Packet(data.StructLayout):
    def __init__(self, data_layout, first=True, last=True):
        layout = (first and { "first": unsigned(1) } or {}) \
               | (last  and { "last":  unsigned(1) } or {})
        super().__init__(layout | {
            "data": data_layout
        })
