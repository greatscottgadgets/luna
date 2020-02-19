#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- exposes packet interfaces. """

import unittest

from nmigen            import Signal, Module, Elaboratable, Memory, Cat, Const, Record
from ...test           import LunaGatewareTestCase, ulpi_domain_test_case, sync_test_case

from .packet           import USBTokenDetector
from ...interface.ulpi import UTMITranslator


class USBDevice(Elaboratable):
    """ Class representing an abstract USB device.

    Can be instantiated directly, and used to build a USB device,
    or can be subclassed to create custom device types.
    """

    def __init__(self, *, bus):
        """
        Parameters:
            bus -- The UTMI or ULPI PHY connection to be used for communications.
        """

        # If this looks more like a ULPI bus than a UTMI bus, translate it.
        if hasattr('rx_valid'):
            self.umti       = UTMITranslator(ulpi=bus)
            self.translator = self.umti

        # Otherwise, use it directly.
        else:
            self.utmi       = bus
            self.translator = None

        #
        # I/O port
        #
        self.sof_detected = Signal()



    def elaborate(self, platform):
        m = Module()

        # If we have a bus translator
        if self.translator:
            m.submodules.translator = self.translator

        # Create our internal token detector.
        m.submodules.token_detector = token_detector = USBTokenDetector(utmi=self.utmi)

        # Pass through select status signals.
        m.d.comb += [
            self.sof_detected  .eq(token_detector.new_frame)
        ]

        return m


if __name__ == "__main__":
    unittest.main()
