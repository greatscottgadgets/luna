#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Utilities for creating LUNA platforms. """


from nmigen import Signal, Record
from nmigen.build.res import ResourceError


class LUNAPlatform:
    """ Mixin that extends nMigen platforms with extra functionality."""


    def request_optional(self, name, number=0, *, dir=None, xdr=None):
        """ Specialized version of .request() for "optional" I/O.

        If the platform has the a resource with the given name, it is requested
        and returned. Otherwise, this method returns a Signal() or Record() that
        will cause the relevant logic to be optimized out.

        This is useful for designs that support multiple platforms; and allows for
        resources such as e.g. LEDs to be omitted on platforms that lack them.
        """

        # Attempt to request the relevant I/O...
        try:
            return self.request(name, number, dir=dir, xdr=xdr)

        # ... and if it does not exist, create an empty stand-in signal. This signal isn't used
        # anywhere else; and thus should typically be optimized away.
        except ResourceError:

            if dir in ("i", "o"):
                return Signal()
            else:
                return Record(["i", "o", "oe"])
