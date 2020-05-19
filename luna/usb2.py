#
# This file is part of LUNA.
#
""" Import shortcuts for our most commonly used functionality. """

# Create shorthands for the most common parts of the library's usb2 gateware.
from .gateware.usb.usb2.device           import USBDevice
from .gateware.usb.usb2.endpoint         import EndpointInterface
from .gateware.usb.usb2.request          import RequestHandlerInterface
from .gateware.usb.usb2.endpoints.stream import USBStreamInEndpoint, USBStreamOutEndpoint


__all__ = [
    'USBDevice',
    'EndpointInterface', 'RequestHandlerInterface',
    'USBStreamInEndpoint'
]
