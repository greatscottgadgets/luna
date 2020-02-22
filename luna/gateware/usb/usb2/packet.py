#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- packetization interfaces. """

import operator
import unittest
import functools

from nmigen            import Signal, Module, Elaboratable, Cat, Record, Array
from ...test           import LunaGatewareTestCase, ulpi_domain_test_case


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
        """ Provides an entire packet transaction at once; for convenience. """
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
            utmi -- The UTMI bus to observe.
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

        def xor_bits(*indices):
            bits = (token[len(token) - 1 - i] for i in indices)
            return functools.reduce(operator.__xor__, bits)

        # Implements the CRC polynomial from the USB specification.
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
                    is_token     = (self.utmi.rx_data[0:2] == self.TOKEN_SUFFIX)
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
            utmi -- The UTMI bus to observe.
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


class USBDataPacketCRC(Elaboratable):
    """ Gateware that computes a running CRC16.

    I/O port:
        I: clear   -- Strobe that restarts the running CRC.

        I: data[8] -- Data input.
        I: valid   -- When high, the `data` input is used to update the CRC.

        O: crc[16] -- CRC16 value.
    """

    def __init__(self, initial_value=0xFFFF):
        """
        Parameters
            initial_value -- The initial value of the CRC shift register; the USB default
                             is used if not provided.
        """

        self._initial_value = initial_value

        #
        # I/O port
        #
        self.clear = Signal()

        self.data  = Signal(8)
        self.valid = Signal()

        self.crc   = Signal(16, reset=initial_value)


    def _generate_next_crc(self, current_crc, data_in):
        """ Generates the next round of a bytewise USB CRC16. """
        xor_reduce = lambda bits : functools.reduce(operator.__xor__, bits)

        # Extracted from the USB spec's definition of the CRC16 polynomial.
        return Cat(
            xor_reduce(data_in)      ^ xor_reduce(current_crc[ 8:16]),
            xor_reduce(data_in[0:7]) ^ xor_reduce(current_crc[ 9:16]),
            xor_reduce(data_in[6:8]) ^ xor_reduce(current_crc[ 8:10]),
            xor_reduce(data_in[5:7]) ^ xor_reduce(current_crc[ 9:11]),
            xor_reduce(data_in[4:6]) ^ xor_reduce(current_crc[10:12]),
            xor_reduce(data_in[3:5]) ^ xor_reduce(current_crc[11:13]),
            xor_reduce(data_in[2:4]) ^ xor_reduce(current_crc[12:14]),
            xor_reduce(data_in[1:3]) ^ xor_reduce(current_crc[13:15]),

            xor_reduce(data_in[0:2]) ^ xor_reduce(current_crc[14:16]) ^ current_crc[0],
            data_in[0] ^ current_crc[1] ^ current_crc[15],
            current_crc[2],
            current_crc[3],
            current_crc[4],
            current_crc[5],
            current_crc[6],
            xor_reduce(data_in) ^ xor_reduce(current_crc[7:16]),
        )




    def elaborate(self, platform):
        m = Module()

        crc = Signal(16, reset=self._initial_value)

        # If we're clearing our CRC in progress, move our holding register back to
        # our initial value.
        with m.If(self.clear):
            m.d.ulpi += crc.eq(self._initial_value)

        # Otherwise, update the CRC whenever we have new data.
        with m.Elif(self.valid):
            m.d.ulpi += crc.eq(self._generate_next_crc(crc, self.data))

        m.d.comb += [
            self.crc  .eq(~crc[::-1])
        ]

        return m


class USBDataPacketDeserializer(Elaboratable):
    """ Gateware that captures USB data packet contents and parallelizes them.

    I/O port:
        O: new_packet -- Strobe that pulses high for a single cycle when a new packet is delivered.
        O: packet[]   -- Packet data for a the most recently received packet.
        O: length[]   -- The length of the packet data presented on the packet[] output.
    """

    DATA_SUFFIX = 0b11

    def __init__(self, *, utmi, max_packet_size=64):
        """
        Parameters:
            utmi -- The UTMI bus to observe.
            max_packet_size -- The maximum packet (payload) size to be deserialized, in bytes.
        """

        self.utmi = utmi
        self._max_packet_size = max_packet_size

        #
        # I/O port
        #
        self.new_packet = Signal()

        self.packet_id  = Signal(4)
        self.packet     = Array(Signal(8, name=f"packet_{i}") for i in range(max_packet_size))
        self.length     = Signal(range(0, max_packet_size + 1))


    def elaborate(self, platform):
        m = Module()

        max_size_with_crc = self._max_packet_size + 2

        # Submodule: CRC16 generator.
        m.submodules.crc = crc = USBDataPacketCRC()
        last_byte_crc = Signal(16)
        last_word_crc = Signal(16)

        # Currently captured PID.
        active_pid         = Signal(4)

        # Active packet transfer.
        active_packet      = Array(Signal(8) for _ in range(max_size_with_crc))
        position_in_packet = Signal(range(0, max_size_with_crc))

        # Keeps track of the
        last_word          = Signal(16)

        # Keep our control signals + strobes un-asserted unless otherwise specified.
        m.d.ulpi += self.new_packet  .eq(0)
        m.d.comb += crc.clear        .eq(0)

        with m.FSM(domain="ulpi"):

            # IDLE -- waiting for a packet to be presented
            with m.State("IDLE"):

                with m.If(self.utmi.rx_active):
                    m.next = "READ_PID"


            # READ_PID -- read the packet's ID.
            with m.State("READ_PID"):
                # Clear our CRC; as we're potentially about to start a new packet.
                m.d.comb += crc.clear.eq(1)

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

                with m.Elif(self.utmi.rx_valid):
                    is_data      = (self.utmi.rx_data[0:2] == self.DATA_SUFFIX)
                    is_valid_pid = (self.utmi.rx_data[0:4] == ~self.utmi.rx_data[4:8])

                    # If this is a data packet, capture it.
                    with m.If(is_valid_pid & is_data):
                        m.d.ulpi += [
                            active_pid          .eq(self.utmi.rx_data),
                            position_in_packet  .eq(0)
                        ]
                        m.next = "CAPTURE_DATA"

                    # Otherwise, ignore this packet.
                    with m.Else():
                        m.next = "IRRELEVANT"


            with m.State("CAPTURE_DATA"):

                # Keep a running CRC of any data observed.
                m.d.comb += [
                    crc.valid  .eq(self.utmi.rx_valid),
                    crc.data   .eq(self.utmi.rx_data)
                ]

                # If we have a new byte of data, capture it.
                with m.If(self.utmi.rx_valid):

                    # If this would over-fill our internal buffer, fail out.
                    with m.If(position_in_packet >= max_size_with_crc):
                        # TODO: potentially signal the babble?
                        m.next = "IRRELEVANT"

                    with m.Else():
                        m.d.ulpi += [
                            active_packet[position_in_packet]  .eq(self.utmi.rx_data),
                            position_in_packet                 .eq(position_in_packet + 1),

                            last_word  .eq(Cat(self.utmi.rx_data, last_word[0:8])),

                            last_word_crc .eq(last_byte_crc),
                            last_byte_crc .eq(crc.crc),
                        ]


                # If this is the end of our packet, validate our CRC and finish.
                with m.If(~self.utmi.rx_active):

                    with m.If(last_word_crc == last_word):
                        m.d.ulpi += [
                            self.packet_id   .eq(active_pid),
                            self.length      .eq(position_in_packet - 2),
                            self.new_packet  .eq(1)
                        ]

                        for i in range(self._max_packet_size):
                            m.d.ulpi += self.packet[i].eq(active_packet[i]),


            # IRRELEVANT -- we've encountered a malformed or non-handshake packet
            with m.State("IRRELEVANT"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

        return m



class USBDataPacketDeserializerTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBDataPacketDeserializer

    @ulpi_domain_test_case
    def test_packet_rx(self):
        yield from self.provide_packet(
            0b11000011,                                     # PID
            0b00100011, 0b01000101, 0b01100111, 0b10001001, # DATA
            0b00011100, 0b00001110                          # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 1, "packet not recognized")
        self.assertEqual((yield self.dut.length),     4)
        self.assertEqual((yield self.dut.packet[0]),  0b00100011)
        self.assertEqual((yield self.dut.packet[1]),  0b01000101)
        self.assertEqual((yield self.dut.packet[2]),  0b01100111)
        self.assertEqual((yield self.dut.packet[3]),  0b10001001)


    @ulpi_domain_test_case
    def test_invalid_rx(self):
        yield from self.provide_packet(
            0b11000011,                                     # PID
            0b11111111, 0b11111111, 0b11111111, 0b11111111, # DATA
            0b00011100, 0b00001110                          # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 0, 'accepted invalid CRC!')


if __name__ == "__main__":
    unittest.main()
