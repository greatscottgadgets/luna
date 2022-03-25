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
__all__ = ['ECP5SerDesPIPE', 'Artix7SerDesPIPE', 'Kintex7SerDesPIPE']

from .backends.ecp5    import ECP5SerDesPIPE
from .backends.artix7  import Artix7SerDesPIPE
from .backends.kintex7 import Kintex7SerDesPIPE
