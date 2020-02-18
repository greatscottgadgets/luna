#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- exposes packet interfaces. """

import unittest

from nmigen            import Signal, Module, Elaboratable, Memory, Cat, Const, Record
from ...test           import LunaGatewareTestCase, ulpi_domain_test_case, sync_test_case

from ...interface.ulpi import UTMITranslator



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


class USBTokenDetectorTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    ULPI_CLOCK_FREQUENCY = 60e6

    def instantiate_dut(self):
        self.utmi = Record([
            ("rx_data",   8),
            ("rx_active", 1),
            ("rx_valid",  1)
        ])
        return USBTokenDetector(utmi=self.utmi)

    def provide_byte(self, byte):
        """ Provides a given byte on the UTMI recieve data for one cycle. """
        yield self.utmi.rx_data.eq(byte)
        yield


    @ulpi_domain_test_case
    def test_valid_token(self):
        dut = self.dut

        # When idle, we should have no new-packet events.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.new_frame), 0)
        self.assertEqual((yield dut.new_token), 0)

        yield self.utmi.rx_active.eq(1)
        yield

        # From: https://usb.org/sites/default/files/crcdes.pdf
        # out to 0x3a, endpoint 0xa => 0xE1 5C BC
        yield self.utmi.rx_valid.eq(1)
        yield from self.provide_byte(0b11100001)
        yield from self.provide_byte(0b00111010)
        yield from self.provide_byte(0b00111101)
        yield self.utmi.rx_active.eq(0)
        yield

        # Validate that we just finished a token.
        yield
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

        yield self.utmi.rx_active.eq(1)
        yield

        # From: https://usb.org/sites/default/files/crcdes.pdf
        # out to 0x3a, endpoint 0xa => 0xE1 5C BC
        yield self.utmi.rx_valid.eq(1)
        yield from self.provide_byte(0xa5)
        yield from self.provide_byte(0b00111010)
        yield from self.provide_byte(0b00111101)
        yield self.utmi.rx_active.eq(0)
        yield

        # Validate that we just finished a token.
        yield
        self.assertEqual((yield dut.new_token), 0)
        self.assertEqual((yield dut.new_frame), 1)

        # Validate that we got the expected address / endpoint.
        self.assertEqual((yield dut.frame), 0x53a)




class USBDevice(Elaboratable):
    """ Class representing an abstract USB device.

    Can be instantiated directly, and used to build a USB device,
    or can be subclassed to create custom device types.
    """

    def __init__(self, *, utmi):
        """
        Parameters:
            utmi -- The UTMI transciever to be used for communications.
        """
        self.utmi = utmi

        #
        # I/O port
        #
        self.sof_detected = Signal()



    def elaborate(self, platform):
        m = Module()

        # Create our internal token detector.
        m.submodules.token_detector = token_detector = USBTokenDetector(utmi=self.utmi)

        # Pass through select status signals.
        m.d.comb += [
            self.sof_detected  .eq(token_detector.new_frame)
        ]

        return m


if __name__ == "__main__":
    unittest.main()
