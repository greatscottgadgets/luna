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
__all__ = ['ECP5SerDesPIPE', 'XC7GTPSerDesPIPE', 'XC7GTXSerDesPIPE']

from .ecp5    import ECP5SerDesPIPE
from .xc7_gtp import XC7GTPSerDesPIPE
from .xc7_gtx import XC7GTXSerDesPIPE
