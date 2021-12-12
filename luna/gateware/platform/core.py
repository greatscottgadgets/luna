#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Utilities for creating LUNA platforms. """

import logging

from amaranth import Signal, Record
from amaranth.build.res import ResourceError, Subsignal, Resource, Pins


class NullPin(Record):
    """ Stand-in for a I/O record. """

    def __init__(self, size=1):
        super().__init__([
            ('i', size),
            ('o', size),
            ('oe', 1),
        ])


class LUNAPlatform:
    """ Mixin that extends Amaranth platforms with extra functionality."""

    name = "unnamed platform"

    def create_usb3_phy(self):
        """ Shortcut that creates a USB3 phy configured for the given platform, if possible. """

        # Ensure our platform has what it needs to create our USB3 PHY.
        if not hasattr(self, "default_usb3_phy"):
            raise ValueError(f"Platform {self.name} has no default USB3 PHY; cannot create one automatically.")

        # Create our PHY, allowing it access to our object.
        return self.default_usb3_phy(self)


    def get_led(self, m, index=0):
        """ Attempts to get an LED for the given platform, where possible.

        If no LED is available, returns a NullPin, so the design can still be generated
        without the relevant LED.
        """

        # First, try to get a simple LED.
        try:
            return self.request("led", index)
        except ResourceError:
            pass

        # Next, try to get an RGB LED, if the platform has one.
        # If we find one, we'll grab only one leg of it, and turn the others off.
        try:
            rgb_led = self.request("rgb_led", index)
            m.d.comb += [
                rgb_led.r.eq(0),
                rgb_led.b.eq(0)
            ]
            return rgb_led.g
        except ResourceError:
            pass


        # Finally, if we've failed to get an LED entirely, return a NullPin stand-in.
        return NullPin()


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


class LUNAApolloPlatform(LUNAPlatform):
    """ Base class for Apollo-based LUNA platforms; includes configuration. """

    def toolchain_program(self, products, name):
        """ Programs the relevant LUNA board via its sideband connection. """

        from apollo_fpga import ApolloDebugger
        from apollo_fpga.ecp5 import ECP5_JTAGProgrammer

        # Create our connection to the debug module.
        debugger = ApolloDebugger()

        # Grab our generated bitstream, and upload it to the FPGA.
        bitstream =  products.get("{}.bit".format(name))
        with debugger.jtag as jtag:
            programmer = ECP5_JTAGProgrammer(jtag)
            programmer.configure(bitstream)


    def _ensure_unconfigured(self, debugger):
        """ Ensures a given FPGA is unconfigured and thus ready for e.g. SPI flashing. """

        from apollo_fpga.ecp5 import ECP5_JTAGProgrammer

        with debugger.jtag as jtag:
            programmer = ECP5_JTAGProgrammer(jtag)
            programmer.unconfigure()


    def toolchain_flash(self, products, name="top"):
        """ Programs the LUNA board's flash via its sideband connection. """

        from apollo_fpga import ApolloDebugger
        from apollo_fpga.ecp5 import ECP5_JTAGProgrammer

        # Create our connection to the debug module.
        debugger = ApolloDebugger()
        self._ensure_unconfigured(debugger)

        # Grab our generated bitstream, and upload it to the .
        bitstream =  products.get("{}.bit".format(name))
        with debugger.jtag as jtag:
            programmer = ECP5_JTAGProgrammer(jtag)
            programmer.flash(bitstream)

        debugger.soft_reset()


    def toolchain_erase(self):
        """ Erases the LUNA board's flash. """

        from apollo_fpga import ApolloDebugger
        from apollo_fpga.ecp5 import ECP5_JTAGProgrammer

        # Create our connection to the debug module.
        debugger = ApolloDebugger()
        self._ensure_unconfigured(debugger)

        with debugger.jtag as jtag:
            programmer = ECP5_JTAGProgrammer(jtag)
            programmer.erase_flash()

        debugger.soft_reset()
