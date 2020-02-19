#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- exposes packet interfaces. """

import unittest

from nmigen            import Signal, Module, Elaboratable, Memory, Cat, Const, Record
from ...test           import LunaGatewareTestCase, ulpi_domain_test_case, sync_test_case

from ...interface.ulpi import UTMITranslator

class USBPacketizerTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    ULPI_CLOCK_FREQUENCY = 60e6

    def instantiate_dut(self):
        self.utmi = Record([
            ("rx_data",   8),
            ("rx_active", 1),
            ("rx_valid",  1)
        ])
        return self.FRAGMENT_UNDER_TEST(utmi=self.utmi)

    def provide_byte(self, byte):
        """ Provides a given byte on the UTMI receive data for one cycle. """
        yield self.utmi.rx_data.eq(byte)
        yield


    def start_packet(self, *, set_rx_valid=True):
        """ Starts a UTMI packet receive. """
        yield self.utmi.rx_active.eq(1)

        if set_rx_valid:
            yield self.utmi.rx_valid.eq(1)

        yield


    def end_packet(self):
        """ Starts a UTMI packet receive. """
        yield self.utmi.rx_active.eq(0)
        yield self.utmi.rx_valid.eq(0)
        yield


    def provide_packet(self, *octets, cycle_after=True):
        yield from self.start_packet()
        for b in octets:
            yield from self.provide_byte(b)
        yield from self.end_packet()

        if cycle_after:
            yield





class USBTokenDetector(Elaboratable):
    """ Gateware that parses token packets and generates relevant events.

    I/O port:
        O  pid[4]      -- The Packet ID of the most recent token.
        O: address[7]  -- The address provided in the most recent token.
        O: endpoint[4] -- The endpoint indicated by the most recent token.
        O: new_token   -- Strobe asserted for a single cycle when a new token
                          packet has been received.

        O: frame[11]   -- The current USB frame number.
        O: new_frame   -- Strobe asserted for a single cycle when a new SOF
                          has been received.
    """

    SOF_PID      = 0b0101
    TOKEN_SUFFIX =   0b01

    def __init__(self, *, utmi):
        """
        Parameters:
            utmi -- The UMTI bus to observe.
        """
        self.utmi = utmi

        #
        # I/O port
        #
        self.pid       = Signal(4)
        self.address   = Signal(7)
        self.endpoint  = Signal(4)
        self.new_token = Signal()

        self.frame     = Signal(11)
        self.new_frame = Signal()


    @staticmethod
    def _generate_crc_for_token(token):
        """ Generates a 5-bit signal equivalent to the CRC check for the provided token packet. """

        import functools, operator

        def xor_bits(*indices):
            bits = (token[len(token) - 1 - i] for i in indices)
            return functools.reduce(operator.__xor__, bits)

        return Cat(
             xor_bits(10, 9, 8, 5, 4, 2),
            ~xor_bits(10, 9, 8, 7, 4, 3, 1),
             xor_bits(10, 9, 8, 7, 6, 3, 2, 0),
             xor_bits(10, 7, 6, 4, 1),
             xor_bits(10, 9, 6, 5, 3, 0)
        )


    def elaborate(self, platform):
        m = Module()

        token_data       = Signal(11)
        current_pid      = Signal.like(self.pid)

        # Keep our strobes un-asserted unless otherwise specified.
        m.d.ulpi += [
            self.new_frame  .eq(0),
            self.new_token  .eq(0)
        ]


        with m.FSM(domain="ulpi"):

            # IDLE -- waiting for a packet to be presented
            with m.State("IDLE"):
                with m.If(self.utmi.rx_active):
                    m.next = "READ_PID"


            # READ_PID -- read the packet's ID, and determine if it's a token.
            with m.State("READ_PID"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

                with m.Elif(self.utmi.rx_valid):
                    is_token     = (self.utmi.rx_data[0:1] == self.TOKEN_SUFFIX)
                    is_valid_pid = (self.utmi.rx_data[0:4] == ~self.utmi.rx_data[4:8])

                    # If we have a valid token, move to capture it.
                    with m.If(is_token & is_valid_pid):
                        m.d.ulpi += current_pid.eq(self.utmi.rx_data)
                        m.next = "READ_TOKEN_0"

                    # Otherwise, ignore this packet as a non-token.
                    with m.Else():
                        m.next = "NON_TOKEN"


            with m.State("READ_TOKEN_0"):

                # If our transaction stops, discard the current read state.
                # We'll ignore token fragments, since it's impossible to tell
                # if they were e.g. for us.
                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

                # If we have a new byte, grab it, and move on to the next.
                with m.Elif(self.utmi.rx_valid):
                    m.d.ulpi += token_data.eq(self.utmi.rx_data)
                    m.next = "READ_TOKEN_1"


            with m.State("READ_TOKEN_1"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

                # Once we've just gotten the second core byte of our token,
                # we can validate our checksum and handle it.
                with m.Elif(self.utmi.rx_valid):
                    expected_crc = self._generate_crc_for_token(
                        Cat(token_data[0:8], self.utmi.rx_data[0:3]))

                    self.crc_out = Signal.like(expected_crc)
                    m.d.comb += self.crc_out.eq(expected_crc)

                    self.crc_in = Signal(11)
                    m.d.comb += self.crc_in.eq(Cat(token_data[0:8], self.utmi.rx_data[0:4]))

                    self.crc_check = Signal(5)
                    m.d.comb += self.crc_check.eq(self.utmi.rx_data[3:8])


                    # If the token has a valid CRC, capture it...
                    with m.If(self.utmi.rx_data[3:8] == expected_crc):
                        m.d.ulpi += token_data[8:].eq(self.utmi.rx_data)
                        m.next = "TOKEN_COMPLETE"

                    # ... otherwise, we'll ignore the whole token, as we can't tell
                    # if this token was meant for us.
                    with m.Else():
                        m.next = "NON_TOKEN"

            # TOKEN_COMPLETE: we've received a full token; and now need to wait
            # for the packet to be complete.
            with m.State("TOKEN_COMPLETE"):

                # Once our receive is complete, use the completed token,
                # and strobe our "new token" signal.
                with m.If(~self.utmi.rx_active):
                    m.next="IDLE"

                    # Special case: if this is a SOF PID, we'll extract
                    # the frame number from this, rather than our typical
                    # token fields.
                    with m.If(current_pid == self.SOF_PID):
                        m.d.ulpi += [
                            self.frame      .eq(token_data),
                            self.new_frame  .eq(1),
                        ]

                    # Otherwise, extract the address and endpoint from the token.
                    with m.Else():
                        m.d.ulpi += [
                            Cat(self.address, self.endpoint).eq(token_data),
                            self.new_token  .eq(1)
                        ]

                # Otherwise, if we get more data, we've received a malformed
                # token -- which we'll ignore.
                with m.Elif(self.utmi.rx_valid):
                    m.next="NON_TOKEN"


            # NON_TOKEN -- we've encountered a non-token packet; wait for it to end
            with m.State("NON_TOKEN"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

        return m


class USBTokenDetectorTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBTokenDetector

    @ulpi_domain_test_case
    def test_valid_token(self):
        dut = self.dut

        # When idle, we should have no new-packet events.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.new_frame), 0)
        self.assertEqual((yield dut.new_token), 0)

        # From: https://usb.org/sites/default/files/crcdes.pdf
        # out to 0x3a, endpoint 0xa => 0xE1 5C BC
        yield from self.provide_packet(0b11100001, 0b00111010, 0b00111101)

        # Validate that we just finished a token.
        self.assertEqual((yield dut.new_token), 1)
        self.assertEqual((yield dut.new_frame), 0)

        # Validate that we got the expected address / endpoint.
        self.assertEqual((yield dut.address), 0x3a)
        self.assertEqual((yield dut.endpoint), 0xa)

        # Ensure that our strobe returns to 0, afterwards.
        yield
        self.assertEqual((yield dut.new_token), 0)


    @ulpi_domain_test_case
    def test_valid_start_of_frame(self):
        dut = self.dut
        yield from self.provide_packet(0b10100101, 0b00111010, 0b00111101)

        # Validate that we just finished a token.
        self.assertEqual((yield dut.new_token), 0)
        self.assertEqual((yield dut.new_frame), 1)

        # Validate that we got the expected address / endpoint.
        self.assertEqual((yield dut.frame), 0x53a)


class USBHandshakeDetector(Elaboratable):
    """ Gateware that detects handshake packets.

    I/O port:
        # Meaningful in either role (host/device).
        O: ack_detected   -- Strobe that pulses high after an ACK handshake is detected.
        O: nak_detected   -- Strobe that pulses high after an NAK handshake is detected.

        # These are only meaningful if we're the host.
        O: stall_detected -- Strobe the pulses high after a STALL handshake is detected.
        O: nyet_detected  -- Strobe the pulses high after a NYET handshake is detected.
    """

    ACK_PID   = 0b0010
    NAK_PID   = 0b1010
    STALL_PID = 0b1110
    NYET_PID  = 0b0110

    def __init__(self, *, utmi):
        """
        Parameters:
            utmi -- The UMTI bus to observe.
        """
        self.utmi = utmi

        #
        # I/O port
        #
        self.ack_detected   = Signal()
        self.nak_detected   = Signal()
        self.stall_detected = Signal()

        self.nyet_detected  = Signal()


    def elaborate(self, platform):
        m = Module()

        active_pid = Signal(4)

        # Keep our strobes un-asserted unless otherwise specified.
        m.d.ulpi += [
            self.ack_detected    .eq(0),
            self.nak_detected    .eq(0),
            self.stall_detected  .eq(0),
            self.nyet_detected   .eq(0),
        ]


        with m.FSM(domain="ulpi"):

            # IDLE -- waiting for a packet to be presented
            with m.State("IDLE"):
                with m.If(self.utmi.rx_active):
                    m.next = "READ_PID"


            # READ_PID -- read the packet's ID.
            with m.State("READ_PID"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

                with m.Elif(self.utmi.rx_valid):
                    is_valid_pid = (self.utmi.rx_data[0:4] == ~self.utmi.rx_data[4:8])

                    # If we have a valid PID, move to capture it.
                    with m.If(is_valid_pid):
                        m.d.ulpi += active_pid.eq(self.utmi.rx_data)
                        m.next = "AWAIT_COMPLETION"

                    # Otherwise, ignore this packet as a non-token.
                    with m.Else():
                        m.next = "IRRELEVANT"


            # TOKEN_COMPLETE: we've received a full token; and now need to wait
            # for the packet to be complete.
            with m.State("AWAIT_COMPLETION"):

                # Once our receive is complete, we can parse the PID
                # and identify the event.
                with m.If(~self.utmi.rx_active):
                    m.d.ulpi += [
                        self.ack_detected    .eq(active_pid == self.ACK_PID),
                        self.nak_detected    .eq(active_pid == self.NAK_PID),
                        self.stall_detected  .eq(active_pid == self.STALL_PID),
                        self.nyet_detected   .eq(active_pid == self.NYET_PID),
                    ]
                    m.next="IDLE"

                # Otherwise, if we get more data, this isn't a valid handshake.
                # Skip this packet as irrelevant.
                with m.Elif(self.utmi.rx_valid):
                    m.next="IRRELEVANT"


            # IRRELEVANT -- we've encountered a malformed or non-handshake packet
            with m.State("IRRELEVANT"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

        return m


class USBHandshakeDetectorTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBHandshakeDetector

    @ulpi_domain_test_case
    def test_ack(self):
        yield from self.provide_packet(0b11010010)
        self.assertEqual((yield self.dut.ack_detected), 1)

    @ulpi_domain_test_case
    def test_nak(self):
        yield from self.provide_packet(0b01011010)
        self.assertEqual((yield self.dut.nak_detected), 1)

    @ulpi_domain_test_case
    def test_stall(self):
        yield from self.provide_packet(0b00011110)
        self.assertEqual((yield self.dut.stall_detected), 1)

    @ulpi_domain_test_case
    def test_nyet(self):
        yield from self.provide_packet(0b10010110)
        self.assertEqual((yield self.dut.nyet_detected), 1)


if __name__ == "__main__":
    unittest.main()
