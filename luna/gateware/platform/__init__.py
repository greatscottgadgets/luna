#
# This file is part of LUNA.
#

from nmigen.vendor.lattice_ecp5 import LatticeECP5Platform

from .luna_r0_1 import LUNAPlatformRev0D1
from .luna_r0_2 import LUNAPlatformRev0D2


# Table mapping LUNA revision numbers to their platform objects.
PLATFORM_FOR_REVISION = {
    (0, 1): LUNAPlatformRev0D1,
    (0, 2): LUNAPlatformRev0D2
}


def get_appropriate_platform() -> LatticeECP5Platform:
    """ Attempts to return the most appropriate platform for the local configuration. """

    from ... import apollo

    # Figure out what hardware revision we're going to connect to...
    version = apollo.ApolloDebugger.detect_connected_version()

    # ... and look up the relevant platform accordingly.
    platform = PLATFORM_FOR_REVISION[version]
    return platform()
