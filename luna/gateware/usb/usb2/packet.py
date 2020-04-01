#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- packetization interfaces. """

import operator
import unittest
import functools

from nmigen            import Signal, Module, Elaboratable, Cat, Array, Const
from nmigen.hdl.rec    import Record, DIR_FANIN, DIR_FANOUT

from .                 import USBSpeed
from ..stream          import USBInStreamInterface
from ...interface.utmi import UTMITransmitInterface
from ...test           import LunaGatewareTestCase, usb_domain_test_case

#
# Interfaces.
#


class HandshakeExchangeInterface(Record):
    """ Record that carries handshakes detected -or- generated between modules. """

    def __init__(self, *, is_detector):
        """
        Parameters:
            is_detector -- If true, this will be considered an interface to a detector that
                           identifies handshakes.
        """
        direction = DIR_FANOUT if is_detector else DIR_FANOUT

        super().__init__([
            ('ack',   1, direction),
            ('nak',   1, direction),
            ('stall', 1, direction),
            ('nyet',  1, direction),
        ])



class DataCRCInterface(Record):
    """ Record providing an interface to a USB CRC-16 generator.

    Components (I = CRC in, O = CRC out):
        I: start   -- Strobe that indicates that a new CRC computation should be started.
        O: crc[16] -- Current CRC value.
    """

    def __init__(self):
        super().__init__([
            ('start', 1,  DIR_FANIN),
            ('crc',   16, DIR_FANOUT)
        ])


class TokenDetectorInterface(Record):
    """ Record providing an interface to a USB token detector.

    Components (I = detector in, O = detector out):
        O  pid[4]             -- The Packet ID of the most recent token.
        O: address[7]         -- The address associated with the relevant token.
        O: endpoint[4]        -- The endpoint indicated by the most recent token.
        O: new_token          -- Strobe asserted for a single cycle when a new token
                                 packet has been received.
        O: ready_for_response -- Strobe asserted for a single cycle one inter-packet
                                 delay after a token packet is complete. Indicates when
                                 the token packet can be responded to.

        O: frame[11]          -- The current USB frame number.
        O: new_frame          -- Strobe asserted for a single cycle when a new SOF
                                 has been received.
    """

    def __init__(self):
        super().__init__([
            ('pid',                4, DIR_FANOUT),
            ('address',            7, DIR_FANOUT),
            ('endpoint',           4, DIR_FANOUT),
            ('new_token',          1, DIR_FANOUT),
            ('ready_for_response', 1, DIR_FANOUT),

            ('frame',             11, DIR_FANOUT),
            ('new_frame',          1, DIR_FANOUT)
        ])


class InterpacketTimerInterface(Record):
    """ Record providing an interface to our interpacket timer.

    See [USB2 7.1.18] and the USBInterpacketTimer gateware for more information.

    Components (I = timer in, O = detector out):
        I: start      -- Strobe that indicates when the timer should be started.
                         Usually started at the end of an Rx or Tx event.

        O: tx_allowed -- Strobe that goes high when it's safe to transmit after an Rx event.
        O: tx_timeout -- Strobe that goes high when the transmit-after-receive window has passed.
        O: rx_timeout -- Strobe that goes high when the receive-after-transmit window has passed.
    """

    def __init__(self):
        super().__init__([
            ('start',      1, DIR_FANIN),

            ('tx_allowed', 1, DIR_FANOUT),
            ('tx_timeout', 1, DIR_FANOUT),
            ('rx_timeout', 1, DIR_FANOUT),
        ])


    def attach(self, *subordinates):
        """ Attaches subordinate interfaces to the given timer interface.

        Each argument added can be:
            An InterpacketTimerInterface, which will be fully connected; or
            A Signal, which will be added to the set of resets.
        """

        start_conditions = []
        fragments = []

        for subordinate in subordinates:

            # If this is an interface, add its start to our list of start conditions,
            # and propagate our timer outputs to it.
            if isinstance(subordinate, self.__class__):
                start_conditions.append(subordinate.start)
                fragments.extend([
                    subordinate.tx_allowed.eq(self.tx_allowed),
                    subordinate.tx_timeout.eq(self.tx_timeout),
                    subordinate.rx_timeout.eq(self.rx_timeout)
                ])

            # If it's a signal, connect it directly as a start signal.
            else:
                start_conditions.append(subordinate)

        # Merge all of our start conditions into a single start condition, and
        # then add that to our fragment list.
        start_condition = functools.reduce(operator.__or__, start_conditions)
        fragments.append(self.start.eq(start_condition))

        return fragments



#
# Gateware.
#


class USBPacketizerTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY  = 60e6

    def instantiate_dut(self, extra_arguments=None):
        self.utmi = Record([
            ("rx_data",   8),
            ("rx_active", 1),
            ("rx_valid",  1)
        ])

        # If we don't have explicit extra arguments, use the base class's.
        if extra_arguments is None:
            extra_arguments = self.FRAGMENT_ARGUMENTS

        return self.FRAGMENT_UNDER_TEST(utmi=self.utmi, **extra_arguments)

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
        *: interface              -- The TokenDetectorInterface that carries our data:
            O: pid[4]             -- The Packet ID of the most recent token.
            O: endpoint[4]        -- The endpoint indicated by the most recent token.
            O: new_token          -- Strobe asserted for a single cycle when a new token
                                     packet has been received.
            O: ready_for_response -- Strobe asserted for a single cycle one inter-packet
                                    delay after a token packet is complete. Indicates when
                                    the token packet can be responded to.
            O: frame[11]   -- The current USB frame number.
            O: new_frame   -- Strobe asserted for a single cycle when a new SOF
                            has been received.

            I: speed[2]    -- The current speed, as a USBSpeed. Used to time interpacket delays.
            I: address[7]  -- If this detector is filtering by address, this is an input that indicates
                                the address that must be matched to generate events.
    """

    SOF_PID      = 0b0101
    TOKEN_SUFFIX =   0b01

    def __init__(self, *, utmi, filter_by_address=True):
        """
        Parameters:
            utmi              -- The UTMI bus to observe.
            filter_by_address -- If true, this detector will only report events for the address
                                 supplied in the address[] field.
        """
        self.utmi = utmi
        self.filter_by_address = filter_by_address

        #
        # I/O port
        #
        self.interface = TokenDetectorInterface()
        self.speed     = Signal(2)
        self.address   = Signal(7)


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
        current_pid      = Signal.like(self.interface.pid)

        # Instantiate a dedicated inter-packet delay timer, which
        # we'll use to generate our `ready_for_response` signal.
        #
        # Giving this unit a timer separate from a device's main
        # timer simplifies the architecture significantly; and
        # removes a primary source of timer contention.
        m.submodules.timer = USBInterpacketTimer()
        timer              = InterpacketTimerInterface()
        m.d.comb += m.submodules.timer.speed.eq(self.speed)

        # Generate our 'ready_for_response' signal whenever our
        # timer reaches a delay that indicates it's safe to respond to a token.
        m.submodules.timer.add_interface(timer)
        m.d.comb += self.interface.ready_for_response.eq(timer.tx_allowed)

        # Keep our strobes un-asserted unless otherwise specified.
        m.d.usb += [
            self.interface.new_frame           .eq(0),
            self.interface.new_token           .eq(0)
        ]

        with m.FSM(domain="usb"):

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
                        m.d.usb += current_pid.eq(self.utmi.rx_data)
                        m.next = "READ_TOKEN_0"

                    # Otherwise, ignore this packet as a non-token.
                    with m.Else():
                        m.next = "IRRELEVANT"


            with m.State("READ_TOKEN_0"):

                # If our transaction stops, discard the current read state.
                # We'll ignore token fragments, since it's impossible to tell
                # if they were e.g. for us.
                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

                # If we have a new byte, grab it, and move on to the next.
                with m.Elif(self.utmi.rx_valid):
                    m.d.usb += token_data.eq(self.utmi.rx_data)
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
                        m.d.usb += token_data[8:].eq(self.utmi.rx_data)
                        m.next = "TOKEN_COMPLETE"

                    # ... otherwise, we'll ignore the whole token, as we can't tell
                    # if this token was meant for us.
                    with m.Else():
                        m.next = "IRRELEVANT"

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
                        m.d.usb += [
                            self.interface.frame      .eq(token_data),
                            self.interface.new_frame  .eq(1),
                        ]

                    # Otherwise, extract the address and endpoint from the token,
                    # and report the captured pid.
                    with m.Else():

                        # If we're filtering by address, only count this token if it's releveant to our address.
                        # Otherwise, always count tokens -- we'll report the address on the output.
                        token_applicable = (token_data[0:7] == self.address) if self.filter_by_address else True
                        with m.If(token_applicable):
                            m.d.usb += [
                                self.interface.pid        .eq(current_pid),
                                self.interface.new_token  .eq(1),

                                Cat(self.interface.address, self.interface.endpoint).eq(token_data)
                            ]

                        # Start our interpacket-delay timer.
                        m.d.comb += timer.start.eq(1)


                # Otherwise, if we get more data, we've received a malformed
                # token -- which we'll ignore.
                with m.Elif(self.utmi.rx_valid):
                    m.next="IRRELEVANT"


            # NON_TOKEN -- we've encountered a non-token packet; wait for it to end
            with m.State("IRRELEVANT"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

        return m


class USBTokenDetectorTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBTokenDetector

    @usb_domain_test_case
    def test_valid_token(self):
        dut = self.dut

        # Assume our device is at address 0x3a.
        yield dut.address.eq(0x3a)

        # When idle, we should have no new-packet events.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.interface.new_frame), 0)
        self.assertEqual((yield dut.interface.new_token), 0)

        # From: https://usb.org/sites/default/files/crcdes.pdf
        # out to 0x3a, endpoint 0xa => 0xE1 5C BC
        yield from self.provide_packet(0b11100001, 0b00111010, 0b00111101)

        # Validate that we just finished a token.
        self.assertEqual((yield dut.interface.new_token), 1)
        self.assertEqual((yield dut.interface.new_frame), 0)

        # Validate that we got the expected PID.
        self.assertEqual((yield dut.interface.pid), 0b0001)

        # Validate that we got the expected address / endpoint.
        self.assertEqual((yield dut.interface.address),  0x3a)
        self.assertEqual((yield dut.interface.endpoint), 0xa )

        # Ensure that our strobe returns to 0, afterwards.
        yield
        self.assertEqual((yield dut.interface.new_token), 0)


    @usb_domain_test_case
    def test_valid_start_of_frame(self):
        dut = self.dut
        yield from self.provide_packet(0b10100101, 0b00111010, 0b00111101)

        # Validate that we just finished a token.
        self.assertEqual((yield dut.interface.new_token), 0)
        self.assertEqual((yield dut.interface.new_frame), 1)

        # Validate that we got the expected address / endpoint.
        self.assertEqual((yield dut.interface.frame), 0x53a)


    @usb_domain_test_case
    def test_token_to_other_device(self):
        dut = self.dut

        # Assume our device is at 0x1f.
        yield dut.address.eq(0x1f)

        # From: https://usb.org/sites/default/files/crcdes.pdf
        # out to 0x3a, endpoint 0xa => 0xE1 5C BC
        yield from self.provide_packet(0b11100001, 0b00111010, 0b00111101)

        # Validate that we did not count this as a token received,
        # as it wasn't for us.
        self.assertEqual((yield dut.interface.new_token), 0)


class USBHandshakeDetector(Elaboratable):
    """ Gateware that detects handshake packets.

    I/O port:
        O: detected.* -- Strobes that indicate which handshakes we're detecting.
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
        self.detected = HandshakeExchangeInterface(is_detector=True)


    def elaborate(self, platform):
        m = Module()

        active_pid = Signal(4)

        # Keep our strobes un-asserted unless otherwise specified.
        m.d.usb += [
            self.detected.ack    .eq(0),
            self.detected.nak    .eq(0),
            self.detected.stall  .eq(0),
            self.detected.nyet   .eq(0),
        ]


        with m.FSM(domain="usb"):

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
                        m.d.usb += active_pid.eq(self.utmi.rx_data)
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
                    m.d.usb += [
                        self.detected.ack    .eq(active_pid == self.ACK_PID),
                        self.detected.nak    .eq(active_pid == self.NAK_PID),
                        self.detected.stall  .eq(active_pid == self.STALL_PID),
                        self.detected.nyet   .eq(active_pid == self.NYET_PID),
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

    @usb_domain_test_case
    def test_ack(self):
        yield from self.provide_packet(0b11010010)
        self.assertEqual((yield self.dut.detected.ack), 1)

    @usb_domain_test_case
    def test_nak(self):
        yield from self.provide_packet(0b01011010)
        self.assertEqual((yield self.dut.detected.nak), 1)

    @usb_domain_test_case
    def test_stall(self):
        yield from self.provide_packet(0b00011110)
        self.assertEqual((yield self.dut.detected.stall), 1)

    @usb_domain_test_case
    def test_nyet(self):
        yield from self.provide_packet(0b10010110)
        self.assertEqual((yield self.dut.detected.nyet), 1)



class USBDataPacketCRC(Elaboratable):
    """ Gateware that computes a running CRC16.

    By default, this module has no connections to the modules that use it.

    These are added using .add_interface(); this module supports an arbitrary
    number of connection interfaces; see .add_interface() for restrictions.

    I/O port:
        I: rx_data[8]   -- Receive data input.
        I: rx_valid     -- When high, the `rx_data` input is used to update the CRC.

        I: tx_data[8]   -- Transmit data input.
        I: tx_valid     -- When high, the `tx_data` input is used to update the CRC.
    """

    def __init__(self, initial_value=0xFFFF):
        """
        Parameters
            initial_value -- The initial value of the CRC shift register; the USB default
                             is used if not provided.
        """

        self._initial_value = initial_value

        # List of interfaces to work with.
        # This list is populated dynamically by calling .add_interface().
        self._interfaces    = []

        #
        # I/O port
        #
        self.clear = Signal()

        self.rx_data  = Signal(8)
        self.rx_valid = Signal()

        self.tx_data  = Signal(8)
        self.tx_valid = Signal()

        self.crc   = Signal(16, reset=initial_value)


    def add_interface(self, interface : DataCRCInterface):
        """ Adds an interface to the CRC generator module.

        Each interface can reset the CRC; and can read the current CRC value.
        No arbitration is performed; it's assumed that no more than one interface
        will be computing a running CRC at at time.
        """
        self._interfaces.append(interface)


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

        # Register that contains the running CRCs.
        crc        = Signal(16, reset=self._initial_value)

        # Signal that contains the output version of our active CRC.
        output_crc = Signal.like(crc)

        # We'll clear our CRC whenever any of our interfaces request it.
        start_signals = (interface.start for interface in self._interfaces)
        clear = functools.reduce(operator.__or__, start_signals)

        # If we're clearing our CRC in progress, move our holding register back to
        # our initial value.
        with m.If(clear):
            m.d.usb += crc.eq(self._initial_value)

        # Otherwise, update the CRC whenever we have new data.
        with m.Elif(self.rx_valid):
            m.d.usb += crc.eq(self._generate_next_crc(crc, self.rx_data))
        with m.Elif(self.tx_valid):
            m.d.usb += crc.eq(self._generate_next_crc(crc, self.tx_data))

        # Convert from our intermediary "running CRC" format into the current CRC-16...
        m.d.comb += output_crc.eq(~crc[::-1])

        # ... and connect it to each of our interfaces.
        for interface in self._interfaces:
            m.d.comb += interface.crc.eq(output_crc)

        return m


class USBDataPacketDeserializer(Elaboratable):
    """ Gateware that captures USB data packet contents and parallelizes them.

    I/O port:
        *: data_crc        -- Connection to the CRC generator.

        O: new_packet      -- Strobe that pulses high for a single cycle when a new packet is delivered.
        O: packet_id[4]    -- The packet ID of the captured PID.

        O: packet[]        -- Packet data for a the most recently received packet.
        O: length[]        -- The length of the packet data presented on the packet[] output.
    """

    DATA_SUFFIX = 0b11

    def __init__(self, *, utmi, max_packet_size=64, create_crc_generator=False):
        """
        Parameters:
            utmi                 -- The UTMI bus to observe.
            max_packet_size      -- The maximum packet (payload) size to be deserialized, in bytes.
            create_crc_generator -- If True, a submodule CRC generator will be created. Excellent for testing.
        """

        self.utmi                 = utmi
        self._max_packet_size     = max_packet_size
        self.create_crc_generator = create_crc_generator

        #
        # I/O port
        #
        self.data_crc    = DataCRCInterface()

        self.new_packet  = Signal()

        self.packet_id   = Signal(4)
        self.packet      = Array(Signal(8, name=f"packet_{i}") for i in range(max_packet_size))
        self.length      = Signal(range(0, max_packet_size + 1))


    def elaborate(self, platform):
        m = Module()

        max_size_with_crc = self._max_packet_size + 2

        # If we're creating an internal CRC generator, create a submodule
        # and hook it up.
        if self.create_crc_generator:
            m.submodules.crc = crc = USBDataPacketCRC()
            crc.add_interface(self.data_crc)

            m.d.comb += [
                crc.rx_data           .eq(self.utmi.rx_data),
                crc.rx_valid          .eq(self.utmi.rx_valid),
                crc.tx_valid           .eq(0)
            ]

        # CRC-16 tracking signals.
        last_byte_crc = Signal(16)
        last_word_crc = Signal(16)

        # Currently captured PID.
        active_pid         = Signal(4)

        # Active packet transfer.
        active_packet      = Array(Signal(8) for _ in range(max_size_with_crc))
        position_in_packet = Signal(range(0, max_size_with_crc))

        # Keeps track of the most recently received word; for CRC comparison.
        last_word          = Signal(16)

        # Keep our control signals + strobes un-asserted unless otherwise specified.
        m.d.usb += self.new_packet      .eq(0)
        m.d.comb += self.data_crc.start  .eq(0)

        with m.FSM(domain="usb"):

            # IDLE -- waiting for a packet to be presented
            with m.State("IDLE"):

                with m.If(self.utmi.rx_active):
                    m.next = "READ_PID"

            # READ_PID -- read the packet's ID.
            with m.State("READ_PID"):
                # Clear our CRC; as we're potentially about to start a new packet.
                m.d.comb += self.data_crc.start.eq(1)

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

                with m.Elif(self.utmi.rx_valid):
                    is_data      = (self.utmi.rx_data[0:2] == self.DATA_SUFFIX)
                    is_valid_pid = (self.utmi.rx_data[0:4] == ~self.utmi.rx_data[4:8])

                    # If this is a data packet, capture it.
                    with m.If(is_valid_pid & is_data):
                        m.d.usb += [
                            active_pid          .eq(self.utmi.rx_data),
                            position_in_packet  .eq(0)
                        ]
                        m.next = "CAPTURE_DATA"

                    # Otherwise, ignore this packet.
                    with m.Else():
                        m.next = "IRRELEVANT"


            with m.State("CAPTURE_DATA"):

                # If we have a new byte of data, capture it.
                with m.If(self.utmi.rx_valid):

                    # If this would over-fill our internal buffer, fail out.
                    with m.If(position_in_packet >= max_size_with_crc):
                        # TODO: potentially signal the babble?
                        m.next = "IRRELEVANT"

                    with m.Else():
                        m.d.usb += [
                            active_packet[position_in_packet]  .eq(self.utmi.rx_data),
                            position_in_packet                 .eq(position_in_packet + 1),

                            last_word     .eq(Cat(last_word[8:], self.utmi.rx_data)),

                            last_word_crc .eq(last_byte_crc),
                            last_byte_crc .eq(self.data_crc.crc),
                        ]


                # If this is the end of our packet, validate our CRC and finish.
                with m.If(~self.utmi.rx_active):

                    with m.If(last_word_crc == last_word):
                        m.d.usb += [
                            self.packet_id   .eq(active_pid),
                            self.length      .eq(position_in_packet - 2),
                            self.new_packet  .eq(1)
                        ]

                        for i in range(self._max_packet_size):
                            m.d.usb += self.packet[i].eq(active_packet[i]),

                        m.next = "IDLE"

            # IRRELEVANT -- we've encountered a malformed or non-handshake packet
            with m.State("IRRELEVANT"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

        return m


class USBDataPacketDeserializerTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBDataPacketDeserializer

    def instantiate_dut(self):
        return super().instantiate_dut(extra_arguments={'create_crc_generator': True})


    @usb_domain_test_case
    def test_packet_rx(self):
        yield from self.provide_packet(
            0b11000011,                                     # PID
            0b00100011, 0b01000101, 0b01100111, 0b10001001, # DATA
            0b00001110, 0b00011100                          # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 1, "packet not recognized")
        self.assertEqual((yield self.dut.length),     4)
        self.assertEqual((yield self.dut.packet[0]),  0b00100011)
        self.assertEqual((yield self.dut.packet[1]),  0b01000101)
        self.assertEqual((yield self.dut.packet[2]),  0b01100111)
        self.assertEqual((yield self.dut.packet[3]),  0b10001001)


    @usb_domain_test_case
    def test_captured_usb_sample(self):
        yield from self.provide_packet(
            0xC3,                                           # PID: Data
            0x00, 0x05, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, # DATA
            0xEB, 0xBC                                      # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 1, "packet not recognized")

    @usb_domain_test_case
    def test_invalid_rx(self):
        yield from self.provide_packet(
            0b11000011,                                     # PID
            0b11111111, 0b11111111, 0b11111111, 0b11111111, # DATA
            0b00011100, 0b00001110                          # CRC
        )

        # Ensure we've gotten a new packet.
        self.assertEqual((yield self.dut.new_packet), 0, 'accepted invalid CRC!')


class USBDataPacketGenerator(Elaboratable):
    """ Module that converts a FIFO-style stream into a USB data packet.

    Handles steps such as PID generation and CRC-16 injection.

    As a special case, if the stream pulses `last` (with valid=1) without pulsing
    `first`, we'll send a zero-length packet.

    I/O port:

        # Control interface:
        I: data_pid[2]  -- The data packet number to use. The potential PIDS are:
                           0 = DATA0, 1 = DATA1, 2 = DATA2, 3 = MDATA; the interface
                           is designed so that most endpoints can tie the MSb to zero
                           and then perform PID toggling by toggling the LSb.

        *: crc          -- Interface to our data CRC generator.
        *: stream       -- Stream input for the raw data to be transmitted.
        *: tx           -- UTMI-subset transmit interface
    """

    def __init__(self, standalone=False):
        """
        Parameter:
            standalone -- If True, this unit will include its internal CRC generator.
                          Perfect for unit testing or debugging.
        """

        self.standalone = standalone

        #
        # I/O port
        #
        self.data_pid     = Signal(2)

        self.crc          = DataCRCInterface()
        self.stream       = USBInStreamInterface()
        self.tx           = UTMITransmitInterface()


    def elaborate(self, platform):
        m = Module()

        # Create a mux that maps our data_pid value to our actual data PID.
        data_pids = Array([
            Const(0xC3, shape=8), # DATA0
            Const(0x4B, shape=8), # DATA1
            Const(0x87, shape=8), # DATA2
            Const(0x0F, shape=8)  # DATAM
        ])

        # Register that stores the final CRC byte.
        # Capturing this before the end of the packet ensures we can still send
        # the correct final CRC byte; even if the CRC generator updates its computation
        # when the first byte of the CRC is transmitted.
        remaining_crc = Signal(8)

        # Flag that stores whether we're sending a zero-length packet.
        is_zlp = Signal()

        # If we're creating an internal CRC generator, create a submodule
        # and hook it up.
        if self.standalone:
            m.submodules.crc = crc = USBDataPacketCRC()
            crc.add_interface(self.crc)

            m.d.comb += [
                crc.rx_valid          .eq(0),

                crc.tx_data           .eq(self.stream.payload),
                crc.tx_valid          .eq(self.tx.ready)
            ]

        with m.FSM(domain="usb"):

            # IDLE -- waiting for an active transmission to start.
            with m.State('IDLE'):

                # We won't consume any data while we're in the IDLE state.
                m.d.comb += self.stream.ready.eq(0)

                # Once a packet starts, we'll need to transmit the data PID.
                with m.If(self.stream.first & self.stream.valid):
                    m.d.usb += is_zlp.eq(0)
                    m.next = "SEND_PID"

                # Special case: if `last` pulses without first, we'll consider this
                # a zero-length packet ("a packet without a first byte").
                with m.Elif(self.stream.last & self.stream.valid):
                    m.d.usb += is_zlp.eq(1)
                    m.next = "SEND_PID"


            # SEND_PID -- prepare for the transaction by sending the data packet ID.
            with m.State('SEND_PID'):

                m.d.comb += [
                    # Prepare for a new payload by starting a new CRC calculation.
                    self.crc.start     .eq(1),

                    # Send the USB packet ID for our data packet...
                    self.tx.data       .eq(data_pids[self.data_pid]),
                    self.tx.valid      .eq(1),

                    # ... and don't consume any data.
                    self.stream.ready  .eq(0)
                ]

                # Advance once the PHY accepts our PID.
                with m.If(self.tx.ready):

                    # If this is a ZLP, we don't have a payload to send.
                    # Skip directly to sending our CRC.
                    with m.If(is_zlp):
                        m.next = 'SEND_CRC_FIRST'

                    # Otherwise, we have a payload. Send it.
                    with m.Else():
                        m.next = 'SEND_PAYLOAD'


            # SEND_PAYLOAD -- send the data payload for our stream
            with m.State('SEND_PAYLOAD'):

                # While sending the payload, we'll essentially connect
                # our stream directly through to the ULPI transmitter.
                m.d.comb += self.stream.bridge_to(self.tx)

                # We'll stop sending once the packet ends, and move on to our CRC.
                with m.If(self.stream.last):
                    m.next = 'SEND_CRC_FIRST'



            # SEND_CRC_FIRST -- send the first byte of the packet's CRC
            with m.State('SEND_CRC_FIRST'):

                # Capture the current CRC for use in the next byte...
                m.d.usb += remaining_crc.eq(self.crc.crc[8:])

                # Send the relevant CRC byte...
                m.d.comb += [
                    self.tx.data       .eq(self.crc.crc[0:8]),
                    self.tx.valid      .eq(1),
                ]

                # ... and move on to the next one.
                m.next = 'SEND_CRC_SECOND'


            # SEND_CRC_LAST -- send the last byte of the packet's CRC
            with m.State('SEND_CRC_SECOND'):

                # Send the relevant CRC byte...
                m.d.comb += [
                    self.tx.data       .eq(remaining_crc),
                    self.tx.valid      .eq(1),
                ]

                # ... and return to idle.
                m.next = 'IDLE'

        return m


class USBDataPacketGeneratorTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY = 60e6

    FRAGMENT_UNDER_TEST = USBDataPacketGenerator
    FRAGMENT_ARGUMENTS  = {'standalone': True}

    def initialize_signals(self):
        # Model our PHY is always accepting data, by default.
        yield self.dut.tx.ready.eq(1)


    @usb_domain_test_case
    def test_simple_data_generation(self):
        dut    = self.dut
        stream = self.dut.stream
        tx     = self.dut.tx

        # We'll request that a simple USB packet be sent. We expect the following data:
        #    0xC3,                                           # PID: Data
        #    0x00, 0x05, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, # DATA
        #    0xEB, 0xBC                                      # CRC

        # Before we send anything, we shouldn't be transmitting.
        self.assertEqual((yield dut.tx.valid), 0)

        # Work with DATA0 packet IDs.
        yield dut.data_pid.eq(0)

        # Start sending our first byte.
        yield stream.first.eq(1)
        yield stream.valid.eq(1)
        yield stream.payload.eq(0x00)
        yield

        # Once our first byte has been provided, our transmission should
        # start (valid=1), and we should see our data PID.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data), 0xc3)

        # We shouldn't consume any data, yet, as we're still
        # transmitting our PID.
        self.assertEqual((yield stream.ready), 0)

        # Drop our first value back to zero, as it should also work as a strobe.
        yield stream.first.eq(0)

        # One cycle later, we should see our first data byte, and our
        # stream should indicate that data was consumed.
        yield
        self.assertEqual((yield tx.data), 0x00)
        self.assertEqual((yield stream.ready), 1)

        # Provide the remainder of our data, and make sure that our
        # output value mirrors it.
        for datum in [0x05, 0x08, 0x00, 0x00, 0x00, 0x00]:
            yield stream.payload.eq(datum)
            yield
            self.assertEqual((yield tx.data), datum)

        # Finally, provide our last data value.
        yield stream.payload.eq(0x00)
        yield stream.last.eq(1)
        yield

        # Drop our stream-valid to zero after the last stream byte.
        yield stream.valid.eq(0)

        # We should now see that we're no longer consuming data...
        yield
        self.assertEqual((yield stream.ready), 0)

        # ... but the transmission is still valid; and now presenting our CRC...
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0xeb)

        # ... which is two-bytes long.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0xbc)

        # Once our CRC is completed, our transmission should stop.
        yield
        self.assertEqual((yield tx.valid), 0)


    @usb_domain_test_case
    def test_zlp_generation(self):
        stream = self.dut.stream
        tx     = self.dut.tx

        # Request a ZLP.
        yield stream.first.eq(0)
        yield stream.last.eq(1)
        yield stream.valid.eq(1)
        yield

        # Drop our last back to zero, immediately.
        yield stream.last.eq(0)

        # Once our first byte has been provided, our transmission should
        # start (valid=1), and we should see our data PID.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data), 0xc3)

        # Drop our stream-valid to zero after the last stream byte.
        yield stream.valid.eq(0)

        # We should now see that we're no longer consuming data...
        yield
        self.assertEqual((yield stream.ready), 0)

        # ... but the transmission is still valid; and now presenting our CRC...
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0x0)

        # ... which is two-bytes long.
        yield
        self.assertEqual((yield tx.valid), 1)
        self.assertEqual((yield tx.data),  0x0)



class USBHandshakeGenerator(Elaboratable):
    """ Module that generates handshake packets, on request.

    I/O port:
        I: issue_ack    -- Pulsed to generate an ACK handshake packet.
        I: issue_nak    -- Pulsed to generate a  NAK handshake packet.
        I: issue_stall  -- Pulsed to generate a STALL handshake.

        # UTMI-equivalent signals,
        *: tx           -- Interface to the relevant UTMI interface.
    """

    # Full contents of an ACK, NAK, and STALL packet.
    # These include the four check bits; which consist of the inverted PID.
    PACKET_ACK   = 0b11010010
    PACKET_NAK   = 0b01011010
    PACKET_STALL = 0b00011110

    def __init__(self):

        #
        # I/O port
        #
        self.issue_ack    = Signal()
        self.issue_nak    = Signal()
        self.issue_stall  = Signal()

        self.tx           = UTMITransmitInterface()


    def elaborate(self, platform):
        m = Module()

        with m.FSM(domain="usb"):

            # IDLE -- we haven't yet received a request to transmit
            with m.State('IDLE'):
                m.d.comb += self.tx.valid.eq(0)

                # Wait until we have an ACK, NAK, or STALL request;
                # Then set our data value to the appropriate PID,
                # in preparation for the next cycle.

                with m.If(self.issue_ack):
                    m.d.usb += self.tx.data  .eq(self.PACKET_ACK),
                    m.next = 'TRANSMIT'

                with m.If(self.issue_nak):
                    m.d.usb += self.tx.data  .eq(self.PACKET_NAK),
                    m.next = 'TRANSMIT'

                with m.If(self.issue_stall):
                    m.d.usb += self.tx.data  .eq(self.PACKET_STALL),
                    m.next = 'TRANSMIT'


            # TRANSMIT -- send the handshake.
            with m.State('TRANSMIT'):
                m.d.comb += self.tx.valid.eq(1)

                # Once we know the transmission will be accepted, we're done!
                # Move back to IDLE.
                with m.If(self.tx.ready):
                    m.next = 'IDLE'

        return m


class USBHandshakeGeneratorTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY = 60e6

    FRAGMENT_UNDER_TEST  = USBHandshakeGenerator


    @usb_domain_test_case
    def test_ack_generation(self):
        dut = self.dut

        # Before we request anything, our data shouldn't be valid.
        self.assertEqual((yield dut.tx.valid), 0)

        # When we request an ACK...
        yield dut.issue_ack.eq(1)
        yield
        yield dut.issue_ack.eq(0)

        # ... we should see an ACK packet on our data lines...
        yield
        self.assertEqual((yield dut.tx.data), USBHandshakeGenerator.PACKET_ACK)

        # ... our transmit request should be valid.
        self.assertEqual((yield dut.tx.valid), 1)

        # It should remain valid...
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.tx.valid), 1)

        # ... until the UTMI transceiver marks it as accepted...
        yield dut.tx.ready.eq(1)
        yield

        # ... when our packet should be marked as invalid.
        yield
        self.assertEqual((yield dut.tx.valid), 0)


    @usb_domain_test_case
    def test_already_ready(self):
        dut = self.dut

        # Start off with our transmitter ready to receive.
        yield dut.tx.ready.eq(1)

        # When we request an ACK...
        yield dut.issue_ack.eq(1)
        yield
        yield dut.issue_ack.eq(0)

        # ... we should see an ACK packet on our data lines...
        yield
        self.assertEqual((yield dut.tx.data), USBHandshakeGenerator.PACKET_ACK)

        # ... our transmit request should be valid...
        self.assertEqual((yield dut.tx.valid), 1)

        # ... and then drop out of being valid after one cycle.
        yield
        self.assertEqual((yield dut.tx.valid), 0)



class USBInterpacketTimer(Elaboratable):
    """ Module that tracks inter-packet timings, enforcing spec-mandated packet gaps.

    I/O port:
        I: speed[2]       -- The device's current operating speed. Should be a USBSpeed
                             enumeration value -- 0 for high, 1 for full, 2 for low.

        Other ports are added dynamically, and control reset conditions (add_reset_condition)
        and timer outputs (get_*_strobe).
    """

    # Per the USB 2.0 and ULPI 1.1 specifications, after receipt:
    #   - A FS/LS device needs to wait 2 bit periods before transmitting; and must
    #     respond before 6.5 bit times pass. [USB2, 7.1.18.1]
    #   - Two FS bit periods is equivalent to 10 ULPI clocks, and two LS periods is
    #     equivalent to 80 ULPI clocks. 6.5 FS bit periods is equivalent to 32 ULPI clocks,
    #     and 6.5 LS bit periods is equivalent to 260 ULPI clocks. [ULPI 1.1, Figure 18].
    #   - A HS device needs to wait 8 HS bit periods before transmitting [USB2, 7.1.18.2].
    #     Each ULPI cycle is 8 HS bit periods, so we'll only need to wait one cycle.

    # TODO: potentially reduce these to account for processing delays?
    HS_RX_TO_TX_DELAY = (  1,  24)
    FS_RX_TO_TX_DELAY = ( 10,  32)
    LS_RX_TO_TX_DELAY = ( 80, 260)

    # Per the USB 2.0 and ULPI 1.1 specifications, after transission:
    #   - A FS/LS can assume it won't receive a response after 16 bit times [USB2, 7.1.18.1].
    #     This is equivalent to 80 ULPI clocks (FS), or 640 ULPI clocks (LS).
    #   - A HS device can assume it won't receive a response after 736 bit times.
    #     This is equivalent to 92 ULPI clocks.
    HS_TX_TO_RX_TIMEOUT =  92
    FS_TX_TO_RX_TIMEOUT =  80
    LS_TX_TO_RX_TIMEOUT = 640


    def __init__(self):

        # List of interfaces to users of this module.
        self._interfaces               = []

        #
        # I/O port
        #
        self.speed = Signal(2)


    def add_interface(self, interface: InterpacketTimerInterface):
        """ Adds a connection to a user of this module.

        This module performs no multiplexing; it's assumed only one interface will be active at a time.
        """
        self._interfaces.append(interface)


    def elaborate(self, platform):
        m = Module()

        # Internal signals representing each of our timeouts.
        rx_to_tx_at_min  = Signal()
        rx_to_tx_at_max  = Signal()
        tx_to_rx_timeout = Signal()

        # Create a counter that will track our interpacket delays.
        # This should be able to count up to our longest delay. We'll allow our
        # counter to be able to increment one past its maximum, and let it saturate
        # there, after the count.
        counter = Signal(range(0, self.LS_TX_TO_RX_TIMEOUT + 2))

        # Reset our timer whenever any of our interfaces request a timer start.
        reset_signals = (interface.start for interface in self._interfaces)
        any_reset = functools.reduce(operator.__or__, reset_signals)

        # When a reset is requested, start the counter from 0.
        with m.If(any_reset):
            m.d.usb += counter.eq(0)
        with m.Elif(counter < self.LS_TX_TO_RX_TIMEOUT + 1):
            m.d.usb += counter.eq(counter + 1)

        #
        # Create our counter-progress strobes.
        # This could be made less repetitive, but spreading it out here
        # makes the documentation above clearer.
        #
        with m.If(self.speed == USBSpeed.HIGH):
            m.d.comb += [
                rx_to_tx_at_min   .eq(counter == self.HS_RX_TO_TX_DELAY[0]),
                rx_to_tx_at_max   .eq(counter == self.HS_RX_TO_TX_DELAY[1]),
                tx_to_rx_timeout  .eq(counter == self.HS_TX_TO_RX_TIMEOUT)
            ]
        with m.Elif(self.speed == USBSpeed.FULL):
            m.d.comb += [
                rx_to_tx_at_min   .eq(counter == self.FS_RX_TO_TX_DELAY[0]),
                rx_to_tx_at_max   .eq(counter == self.FS_RX_TO_TX_DELAY[1]),
                tx_to_rx_timeout  .eq(counter == self.FS_TX_TO_RX_TIMEOUT)
            ]
        with m.Else():
            m.d.comb += [
                rx_to_tx_at_min   .eq(counter == self.LS_RX_TO_TX_DELAY[0]),
                rx_to_tx_at_max   .eq(counter == self.LS_RX_TO_TX_DELAY[1]),
                tx_to_rx_timeout  .eq(counter == self.LS_TX_TO_RX_TIMEOUT)
            ]

        # Tie our strobes to each of our consumers.
        for interface in self._interfaces:
            m.d.comb += [
                interface.tx_allowed.eq(rx_to_tx_at_min),
                interface.tx_timeout.eq(rx_to_tx_at_max),
                interface.rx_timeout.eq(tx_to_rx_timeout)
            ]


        return m


class USBInterpacketTimerTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY = 60e6

    def instantiate_dut(self):
        dut = USBInterpacketTimer()

        # Create our primary timer interface.
        self.interface = InterpacketTimerInterface()
        dut.add_interface(self.interface)

        return dut


    def initialize_signals(self):
        # Assume FS for our tests, unless overridden.
        yield self.dut.speed(USBSpeed.FULL)


    def test_resets_and_delays(self):
        yield from self.advance_cycles(4)
        interface = self.interface

        # Trigger a cycle reset.
        yield interface.start.eq(1)
        yield
        yield interface.start.eq(0)

        # We should start off with no timer outputs high.
        self.assertEqual((yield interface.tx_allowed), 0)
        self.assertEqual((yield interface.tx_timeout), 0)
        self.assertEqual((yield interface.rx_timeout), 0)

        # 10 cycles later, we should see our first timer output.
        yield from self.advance_cycles(10)
        self.assertEqual((yield interface.tx_allowed), 1)
        self.assertEqual((yield interface.tx_timeout), 0)
        self.assertEqual((yield interface.rx_timeout), 0)

        # 22 cycles later (32 total), we should see our second timer output.
        yield from self.advance_cycles(22)
        self.assertEqual((yield interface.tx_allowed), 0)
        self.assertEqual((yield interface.tx_timeout), 1)
        self.assertEqual((yield interface.rx_timeout), 0)

        # 58 cycles later (80 total), we should see our third timer output.
        yield from self.advance_cycles(22)
        self.assertEqual((yield interface.tx_allowed), 0)
        self.assertEqual((yield interface.tx_timeout), 0)
        self.assertEqual((yield interface.rx_timeout), 1)

        # Ensure that the timers don't go high again.
        for _ in range(32):
            self.assertEqual((yield self.rx_to_tx_min),     0)
            self.assertEqual((yield self.rx_to_tx_max),     0)
            self.assertEqual((yield self.tx_to_rx_timeout), 0)


if __name__ == "__main__":
    unittest.main()
