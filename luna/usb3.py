#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Import shortcuts for our most commonly used functionality. """

# Create shorthands for the most common parts of the library's usb3 gateware.
from .gateware.usb.usb3.device              import USBSuperSpeedDevice
from .gateware.usb.usb3.application.request import SuperSpeedRequestHandlerInterface, SuperSpeedRequestHandler
from .gateware.usb.usb3.endpoints.stream    import SuperSpeedStreamInEndpoint

__all__ = ['USBSuperSpeedDevice', 'SuperSpeedRequestHandler']
