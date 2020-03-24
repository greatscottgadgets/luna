
from enum import IntEnum


class USBSpeed(IntEnum):
    """ Enumeration representing USB speeds. Matches UTMI xcvr_select constants. """

    HIGH = 0b00
    FULL = 0b01
    LOW  = 0b10
