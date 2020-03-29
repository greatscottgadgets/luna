#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- control transfer components. """

import unittest

from nmigen            import Signal, Module, Elaboratable, Cat, Record, Array
from ...test           import LunaGatewareTestCase, usb_domain_test_case

from .packet           import DataCRCInterface
from .request          import USBSetupDecoder


class USBControlEndpoint(Elaboratable):
    """ Base class for USB control endpoint implementers.

    I/O port:
        # CRC connections.
        O: start_crc    -- Indicates that a new data CRC computation should be started.
        I: data_crc[16] -- Input from the relevant device's data-CRC module.

        # Handshake connections.
        O: issue_ack    -- Strobe; pulses high when the endpoint wants to issue an ACK handshake.
        O: issue_nak    -- Strobe; pulses high when the endpoint wants to issue a  NAK handshake.
        O: issue_stall  -- Strobe; pulses high when the endpoint wants to issue a  STALL handshake.

        # Diagnostic I/O.
        last_request[8] -- Request number of the last request.
    """

    def __init__(self, *, utmi, tokenizer, timer):
        """
        Parameters:
            utmi       -- The UTMI bus we'll monitor for data. We'll consider this read-only.
            tokenizer  -- The USBTokenDetector detecting token packets for us. Considered read-only.
            timer      -- The interpacket timer we'll use for timing.
        """
        self.utmi         = utmi
        self.tokenizer    = tokenizer
        self.timer        = timer

        # Create our setup decoder.
        # Note that this must be created during this initialization; as its initialization
        # makes subordinate connections.
        self.setup_decoder = USBSetupDecoder(utmi=self.utmi, tokenizer=self.tokenizer, timer=self.timer)

        #
        # I/O Port
        #
        self.data_crc     = DataCRCInterface()

        self.issue_ack    = Signal()
        self.issue_nak    = Signal()
        self.issue_stall  = Signal()

        # Debug outputs
        self.last_request = Signal(8)
        self.new_packet   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Create our SETUP packet decoder.
        m.submodules.setup_decoder = self.setup_decoder
        m.d.comb += self.data_crc.connect(self.setup_decoder.data_crc)

        # Automatically acknowledge any valid SETUP packet.
        m.d.comb += self.issue_ack.eq(self.setup_decoder.ack)

        # Debug output.
        m.d.comb += [
            self.last_request  .eq(self.setup_decoder.request),
            self.new_packet    .eq(self.setup_decoder.new_packet),
        ]

        return m
