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
        O: issue_ack   -- Pulses high when the endpoint wants to issue an ACK handshake.
        O: issue_nak   -- Pulses high when the endpoint wants to issue a  NAK handshake.
        O: issue_stall -- Pulses high when the endpoint wants to issue a  STALL handshake.

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
        self.issue_ack    = Signal()
        self.issue_nak    = Signal()
        self.issue_stall  = Signal()

        # Debug outputs
        self.last_request = Signal(8)
        self.new_packet   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Create our SETUP packet decoder.
        m.submodules.setup_decoder = setup_decoder = \
             USBSetupDecoder(utmi=self.utmi, tokenizer=self.tokenizer)

        # Automatically acknowledge any valid SETUP packet.
        m.d.comb += self.issue_ack.eq(setup_decoder.ack)

        # Debug output.
        m.d.comb += [
            self.last_request  .eq(setup_decoder.request),
            self.new_packet    .eq(setup_decoder.new_packet),
        ]

        return m
