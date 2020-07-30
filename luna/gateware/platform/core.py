#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Utilities for creating LUNA platforms. """

import logging

from nmigen import Signal, Record
from nmigen.build.res import ResourceError, Subsignal, Resource, Pins


#
# This is temporary until we have the equivalent of this merged into nmigen-boards.
#
def ULPIResource(*args, data, clk, dir, nxt, stp, rst=None,
            clk_dir='i', invert_rst=False, attrs=None, conn=None):
    assert clk_dir in ('i', 'o',)

    io = []
    io.append(Subsignal("data", Pins(data, dir="io", conn=conn, assert_width=8)))
    io.append(Subsignal("clk", Pins(clk, dir=clk_dir, conn=conn, assert_width=1)))
    io.append(Subsignal("dir", Pins(dir, dir="i", conn=conn, assert_width=1)))
    io.append(Subsignal("nxt", Pins(nxt, dir="i", conn=conn, assert_width=1)))
    io.append(Subsignal("stp", Pins(stp, dir="o", conn=conn, assert_width=1)))
    if rst is not None:
        io.append(Subsignal("rst", Pins(rst, dir="o", invert=invert_rst,
            conn=conn, assert_width=1)))
    if attrs is not None:
        io.append(attrs)
    return Resource.family(*args, default_name="usb", ios=io)


class LUNAPlatform:
    """ Mixin that extends nMigen platforms with extra functionality."""

    def request_optional(self, name, number=0, *args, default, expected=False, **kwargs):
        """ Specialized version of .request() for "optional" I/O.

        If the platform has the a resource with the given name, it is requested
        and returned. Otherwise, this method returns the value provided in the default argument.

        This is useful for designs that support multiple platforms; and allows for
        resources such as e.g. LEDs to be omitted on platforms that lack them.

        Parameters
        ----------
        default: any
            The value that is returned in lieu of the relevant resources if the resource does not exist.
        expected: bool, optional
            If explicitly set to True, this function will emit a warning when the given pin is not present.
        """

        try:
            return self.request(name, number, *args, **kwargs)
        except ResourceError:
            log = logging.warnings if expected else logging.debug
            log(f"Skipping resource {name}/{number}, as it is not present on this platform.")
            return default
