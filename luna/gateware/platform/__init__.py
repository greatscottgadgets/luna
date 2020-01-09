
from .luna_r0_1 import LUNAPlatformR01


def get_appropriate_platform():
    """ Attempts to return the most appropriate platform for the local configuration. """

    # For now, we only have R01, so use that.
    return LUNAPlatformR01()
