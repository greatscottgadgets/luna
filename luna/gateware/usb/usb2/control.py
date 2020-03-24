#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- control transfer components. """

import unittest

from nmigen            import Signal, Module, Elaboratable, Cat, Record, Array
from ...test           import LunaGatewareTestCase, ulpi_domain_test_case

from .request          import USBSetupDecoder


class USBControlEndpoint(Elaboratable):
    """ Base class for USB control endpoint implementers.

    I/O port:


        # Diagnostic I/O.
        last_request[8] -- Request number of the last request.
    """

    def __init__(self, *, utmi, tokenizer):
        """
        Parameters:
            utmi       -- The UTMI bus we'll monitor for data. We'll consider this read-only.
            tokenizer  -- The USBTokenDetector detecting token packets for us. Considered read-only.
        """
        self.utmi = utmi
        self.tokenizer = tokenizer

        #
        # I/O Port
        #

        # Debug outputs
        self.last_request = Signal(8)
        self.new_packet   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Create our SETUP packet decoder.
        m.submodules.setup_decoder = setup_decoder = \
             USBSetupDecoder(utmi=self.utmi, tokenizer=self.tokenizer)

        # Debug output.
        m.d.comb += [
            self.last_request  .eq(setup_decoder.request),
            self.new_packet    .eq(setup_decoder.new_packet)
        ]

        return m
