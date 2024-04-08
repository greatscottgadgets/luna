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

from typing import Optional

from amaranth import Record

from .core import NullPin, LUNAPlatform


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


def get_appropriate_platform() -> LUNAPlatform:
    """ Attempts to return the most appropriate platform for the local configuration. """

    # If we have a LUNA_PLATFORM variable, use it.
    if os.getenv("LUNA_PLATFORM"):
        return _get_platform_from_string(os.getenv("LUNA_PLATFORM"))

    # Otherwise, try to detect an Apollo-based platform.
    platform_string, fpga_device = get_apollo_platform()
    if platform_string is None:
        raise RuntimeError(
            "Unable to autodetect a supported platform. "
            "The LUNA_PLATFORM environment variable must be set.")
    platform = _get_platform_from_string(platform_string)
    
    # If possible, override the platform's device type with the detected FPGA.
    if fpga_device is not None:
        platform.device = fpga_device
    
    return platform


def get_apollo_platform() -> (Optional[str], Optional[str]):
    """ Attempts to return a platform string for a connected Apollo-based device. """

    # Try to import Apollo and look for a debug interface.
    try:
        import apollo_fpga
        debugger = apollo_fpga.ApolloDebugger()
    except (ImportError, apollo_fpga.DebuggerNotFound):
        return None, None

    # Retrieve the version of the attached device.
    version = debugger.detect_connected_version()

    # Try to auto-detect the attached FPGA device. This can be
    # used to override the default platform's device type.
    try:
        fpga_type = debugger.get_fpga_type()
    except IOError:
        fpga_type = None

    # Check if relevant modules provide a platform string.
    try:
        import cynthion.gateware
        return cynthion.gateware.APOLLO_PLATFORMS[version], fpga_type
    except (ImportError, AttributeError, KeyError):
        pass
    try:
        import luna_boards
        return luna_boards.APOLLO_PLATFORMS[version], fpga_type
    except (ImportError, AttributeError, KeyError):
        pass

    # If none of the above modules produced a match, no platform is known.
    return None, None


class NullPin(Record):
    """ Stand-in for a I/O record. """

    def __init__(self, size=1):
        super().__init__([
            ('i', size),
            ('o', size),
            ('oe', 1),
        ])
