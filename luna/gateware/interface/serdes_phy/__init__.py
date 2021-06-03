#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code adapted from ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" SerDes-based USB3 PIPE PHY. """

#
# Quick-use aliases
#
__all__ = ['SerDesPHY', 'LunaECP5SerDes', 'LunaArtix7SerDes']

# Core hardware.
from .phy import SerDesPHY

# Backends.
from .backends.ecp5   import LunaECP5SerDes
from .backends.artix7 import LunaArtix7SerDes
