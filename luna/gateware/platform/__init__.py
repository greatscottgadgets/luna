#
# This file is part of LUNA.
#
# Copyright (c) 2020-2023 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os
import sys
import logging

import importlib
import importlib.util

from amaranth import Record
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform

from .cynthion_r0_1 import CynthionPlatformRev0D1
from .cynthion_r0_2 import CynthionPlatformRev0D2
from .cynthion_r0_3 import CynthionPlatformRev0D3
from .cynthion_r0_4 import CynthionPlatformRev0D4
from .cynthion_r0_5 import CynthionPlatformRev0D5
from .cynthion_r0_6 import CynthionPlatformRev0D6
from .cynthion_r0_7 import CynthionPlatformRev0D7
from .cynthion_r1_0 import CynthionPlatformRev1D0
from .cynthion_r1_1 import CynthionPlatformRev1D1
from .daisho    import DaishoPlatform
from .amalthea  import AmaltheaPlatformRev0D1

from .core      import NullPin



# Stores the latest platform; for reference / automagic.
LATEST_PLATFORM = CynthionPlatformRev1D1


# Table mapping hardware revision numbers to their platform objects.
PLATFORM_FOR_REVISION = {
    (0,   1): CynthionPlatformRev0D1,
    (0,   2): CynthionPlatformRev0D2,
    (0,   3): CynthionPlatformRev0D3,
    (0,   4): CynthionPlatformRev0D4,
    (0,   5): CynthionPlatformRev0D5,
    (0,   6): CynthionPlatformRev0D6,
    (0,   7): CynthionPlatformRev0D7,
    (1,   0): CynthionPlatformRev1D0,
    (1,   1): CynthionPlatformRev1D1,
    (254, 1): AmaltheaPlatformRev0D1,
    (255, 0): DaishoPlatform
}

def _get_platform_from_string(platform):
    """ Attempts to get the most appropriate platform given a <module>:<class> specification."""

    # Attempt to split the platform into a module / name.
    module, _, name = platform.partition(':')
    if (not module) or (not name):
        raise TypeError("LUNA_PLATFORM must be in <module path>:<class name> format.")


    # If we have a filename, load the module from our file.
    module_path = os.path.expanduser(module)
    if os.path.isfile(module_path):

        # Get a reference to the platform module to be loaded...
        import_path     = "luna.gateware.platform.dynamic"
        spec            = importlib.util.spec_from_file_location(import_path, module_path)
        platform_module = importlib.util.module_from_spec(spec)

        # ... and pull in its code .
        spec.loader.exec_module(platform_module)


    # Otherwise, try to parse it as a module path.
    else:
        platform_module = importlib.import_module(module)

    # Once we have the relevant module, extract our class from it.
    platform_class = getattr(platform_module, name)
    return platform_class()


def get_appropriate_platform() -> LatticeECP5Platform:
    """ Attempts to return the most appropriate platform for the local configuration. """

    # If we have a LUNA_PLATFORM variable, use it instead of autonegotiating.
    if os.getenv("LUNA_PLATFORM"):
        return _get_platform_from_string(os.getenv("LUNA_PLATFORM"))

    import apollo_fpga

    try:
        # Figure out what hardware revision we're going to connect to...
        debugger = apollo_fpga.ApolloDebugger()
        version = debugger.detect_connected_version()

        # ... and look up the relevant platform accordingly.
        platform = PLATFORM_FOR_REVISION[version]()

        # Finally, override the platform's device type with the FPGA we detect
        # as being present on the relevant board. (Note that this auto-detection
        # only works if we're programming a connected device; otherwise, we'll
        # need to use the custom-platform environment variables.)
        platform.device = debugger.get_fpga_type()

        # Explicitly close the debugger connection, as Windows doesn't allow you to
        # re-claim the USB device if it's still open.
        debugger.close()

        return platform


    # If we don't have a connected platform, fall back to the latest platform.
    except apollo_fpga.DebuggerNotFound:
        platform = LATEST_PLATFORM()

        logging.warning(f"Couldn't auto-detect connected platform. Assuming {platform.name}.")
        return platform


class NullPin(Record):
    """ Stand-in for a I/O record. """

    def __init__(self, size=1):
        super().__init__([
            ('i', size),
            ('o', size),
            ('oe', 1),
        ])
