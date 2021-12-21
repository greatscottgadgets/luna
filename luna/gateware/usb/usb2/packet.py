#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Contains the gatware module necessary to interpret and generate low-level USB packets. """


import operator
import unittest
import functools

from amaranth          import Signal, Module, Elaboratable, Cat, Array, Const
from amaranth.hdl.rec  import Record, DIR_FANIN, DIR_FANOUT

from .                 import USBSpeed, USBPacketID
from ..stream          import USBInStreamInterface, USBOutStreamInterface
from ...interface.utmi import UTMITransmitInterface
from ...test           import LunaGatewareTestCase, usb_domain_test_case

#
# Interfaces.
#


class HandshakeExchangeInterface(Record):
    """ Record that carries handshakes detected -or- generated between modules.

    Attributes
    ----------
    ack: Signal()
        When connected to a generator, pulsing this strobe will trigger generating of an ACK.
        When connected to a detector, this strobe will be pulsed when an ACK is detected from the host.
    nak: Signal()
        When connected to a generator, pulsing this strobe will trigger generating of an NAK.
        When connected to a detector, this strobe will be pulsed when an NAK is detected from the host.
    stall: Signal()
        When connected to a generator, pulsing this strobe will trigger generation of a STALL.
        Unused in a detector, currently.
    nyet: Signal()
        When connected to a generator, pulsing this strobe will trigger generation of a NYET.
        Unused in a detector, currently.

    Parameters
    ----------
    is_detector: bool
        If true, this will be considered an interface to a detector that identifies handshakes.
        Otherwise, this will be considered an interface to a generator that accepts handshake requests.
    """

    def __init__(self, *, is_detector):
        direction = DIR_FANOUT if is_detector else DIR_FANOUT

        super().__init__([
            ('ack',   1, direction),
            ('nak',   1, direction),
            ('stall', 1, direction),
            ('nyet',  1, direction),
        ])



class DataCRCInterface(Record):
    """ Record providing an interface to a USB CRC-16 generator.

    Attributes
    ----------
    start: Signal(), input to CRC generator
        Strobe that indicates that a new CRC computation should be started.
    crc: Signal(), output from CRC generator
        The current CRC-16 value; updated with each sent or received byte.
    """

    def __init__(self):
        super().__init__([
            ('start', 1,  DIR_FANIN),
            ('crc',   16, DIR_FANOUT)
        ])


class TokenDetectorInterface(Record):
    """ Record providing an interface to a USB token detector.

    Attributes
    ----------
    pid: Signal(4), detector output
        The Packet ID of the most recent token.
    address: Signal(7), detector output
        The address associated with the relevant token.
    endpoint: Signal(4), detector output
        The endpoint indicated by the most recent token.

    new_token: Signal(), detector output
        Strobe asserted for a single cycle when a new token packet has been received.
    ready_for_response: Signal(), detector output
        Strobe asserted for a single cycle one inter-packet delay after a token packet is complete.
        Indicates when the token packet can be responded to.

    frame: Signal(11), detector output
        The current USB frame number.
    new_frame: Signal(), detector output
        Strobe asserted for a single cycle when a new SOF has been received.

    is_in: Signal(), detector output
        High iff the current token is an IN.
    is_out: Signal(), detector output
        High iff the current token is an OUT.
    is_setup: Signal(), detector output
        High iff the current token is a SETUP.
    is_ping: Signal(), detector output
        High iff the current token is a PING.
    """

    def __init__(self):
        super().__init__([
            ('pid',                4, DIR_FANOUT),
            ('address',            7, DIR_FANOUT),
            ('endpoint',           4, DIR_FANOUT),
            ('new_token',          1, DIR_FANOUT),
            ('ready_for_response', 1, DIR_FANOUT),

            ('frame',             11, DIR_FANOUT),
            ('new_frame',          1, DIR_FANOUT),

            ('is_in',              1, DIR_FANOUT),
            ('is_out',             1, DIR_FANOUT),
            ('is_setup',           1, DIR_FANOUT),
            ('is_ping',            1, DIR_FANOUT),
        ])


class InterpacketTimerInterface(Record):
    """ Record providing an interface to our interpacket timer.

    See [USB2.0: 7.1.18] and the USBInterpacketTimer gateware for more information.

    Attributes
    ----------
    start: Signal(), input to timer
        Strobe that indicates when the timer should be started. Usually started at the end of an Rx or Tx event.

    tx_allowed: Signal(), output from timer
        Strobe that goes high when it's safe to transmit after an Rx event.
    tx_timeout: Signal(), output from timer
        Strobe that goes high when the transmit-after-receive window has passed.
    rx_timeout: Signal(), output from timer
        Strobe that goes high when the receive-after-transmit window has passed.
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

        Parameters
        ----------
        subordinates: [InterpacketTimerInterface, Signal]
            Each :class:`InterpacketTimerInterface` is provided will be fully connected to a given
            timer interface. Each ``Signal`` provided will be interpreted as a timer reset, and added
            to the list of all resets.
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

    Attributes
    ----------
    interface: TokenDetectorInterface
        The interface that contains token detection events, and information about detected tokens.
    speed: Signal(2), input
        Carries a ``USBSpeed`` constant identifying the device's current operating speed.
    address: Signal(7), input -or- output
        If :parameter:``filter_by_address`` is true, this is an input that filters our event detector so
        it only reports tokens directed at a given address.
        If ``filter_by_address`` is false, this is an output that contains the address of the most
        recent token.


    Parameters
    ----------
        utmi: UTMIInterface
            The UTMI bus to observe.
        filter_by_address: bool
            If true, this detector will only report events for the address supplied in the address[] field.
    """

    SOF_PID      = 0b0101
    TOKEN_SUFFIX =   0b01

    def __init__(self, *, utmi, filter_by_address=True, domain_clock=60e6, fs_only=False):
        self.utmi = utmi
        self.filter_by_address = filter_by_address
        self._domain_clock = domain_clock
        self._fs_only = fs_only

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
        m.submodules.timer = USBInterpacketTimer(domain_clock=self._domain_clock, fs_only=self._fs_only)
        timer              = InterpacketTimerInterface()
        m.d.comb += m.submodules.timer.speed.eq(self.speed)

        # Generate our 'ready_for_response' signal whenever our
        # timer reaches a delay that indicates it's safe to respond to a token.
        m.submodules.timer.add_interface(timer)
        m.d.comb += self.interface.ready_for_response.eq(timer.tx_allowed)

        # Generate our convenience status signals.
        m.d.comb += [
            self.interface.is_in     .eq(self.interface.pid == USBPacketID.IN),
            self.interface.is_out    .eq(self.interface.pid == USBPacketID.OUT),
            self.interface.is_setup  .eq(self.interface.pid == USBPacketID.SETUP),
            self.interface.is_ping   .eq(self.interface.pid == USBPacketID.PING)
        ]

        # Keep our strobes un-asserted unless otherwise specified.
        m.d.usb += [
            self.interface.new_frame  .eq(0),
            self.interface.new_token  .eq(0)
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
                    is_normal_token = (self.utmi.rx_data[0:2] == self.TOKEN_SUFFIX)
                    is_ping_token   = (self.utmi.rx_data[0:4] == USBPacketID.PING)
                    is_valid_pid    = (self.utmi.rx_data[0:4] == ~self.utmi.rx_data[4:8])

                    # If we have a valid token, move to capture it.
                    # Note that we have two categories of token we'll accept: normal tokens (IN, OUT, SETUP, SOF),
                    # and our SPECIAL category tokens (e.g. PING), which have a separate PID suffix.
                    with m.If((is_normal_token | is_ping_token) & is_valid_pid):
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

                        # If we don't count the token, clear the state so we don't act on following packets.
                        with m.Else():
                            m.d.usb += self.interface.pid.eq(0)


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

    Attributes
    -----------
    detected: HandshakeExchangeInterface
        Strobes that indicate which handshakes we're detecting.

    Parameters
    ----------
    utmi: [UTMIInterface, UTMITranslator]
        The UTMI interface to listen on.
    """

    ACK_PID   = 0b0010
    NAK_PID   = 0b1010
    STALL_PID = 0b1110
    NYET_PID  = 0b0110

    def __init__(self, *, utmi):
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
    """ Gateware that computes a running CRC-16.

    By default, this module has no connections to the modules that use it.

    These are added using :attr:`add_interface`; this module supports an arbitrary
    number of connection interfaces; see :attr:`add_interface()` for restrictions.

    Attributes
    ----------
    rx_data: Signal(8), input
        Receive data input; can be carried directly from a UTMI interface.
    rx_valid: Signal(), input
        Receive validity signal; can be carried directly from a UTMI interface.

    tx_data: Signal(8), input
        Transmit data input; can be carried directly from a UTMI interface.
    tx_valid: Signal(), input
        When high, the `tx_data` input is used to update the CRC.

    Parameters
    ----------
    initial_value: [int, Const]
            The initial value of the CRC shift register; the USB default is used if not provided.
    """

    def __init__(self, initial_value=0xFFFF):

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

        Parameters
        ----------
        interface: DataCRCInterface
            The interface to be added; accepts control signals from other modules, and
            brings CRC output to them. This method can be called multiple times to generate
            multiplpe CRCs.
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


class USBDataPacketReceiver(Elaboratable):
    """ Gateware that converts received USB data packets into a data-stream packets.

    It's important to note that packet payloads are mostly directly carried over from UTMI.
    Since USB data is received -prior- to its CRC, one cannot know if a packet is valid until
    after it has been compeltely received. As a result, this interface will generate data of
    unknown validity, followed by a strobe on either :attr:`packet_complete` or :attr:`crc_mismatch`.
    The receiving interface must be prepared to handle :attr:`crc_mismatch` by discarding the received
    data.


    Attributes
    ----------
    data_crc: DataCRCInterface
        Connection to the CRC generator.
    timer: InterpacketTimerInterface
        Connection to our interpacket timer.
    stream: USBOutDataStream, output
        Stream that carries captured packet data.

    active_pid: Signal(4), output
        The PID of the data currently being received.
    packet_id: Signal(4), output
        The packet ID of the most recently captured PID. Becomes valid simultaneous to a strobe on
        :attr:`packet_complete` or :attr:`crc_mismatch`.

    packet_complete: Signal(), output
        Strobe that pulses high when a new packet is delivered with a valid CRC.
    crc_mismatch: Signal(), output
        Strobe that pulses high when the given packet has a CRC mismatch; and thus the data
        received this far should be discarded.
    ready_for_response: Signal(), output
        Strobe that indicates that an inter-packet delay has passed since :attr:`packet_complete`,
        and thus we're now ready to respond with a handshake.

    Parameters
    ----------
    utmi: UTMIInterface, or equivalent
        The UTMI bus to observe.
    max_packet_size: int
        The maximum packet (payload) size to be deserialized, in bytes.

    standalone: bool
        Debug value. If True, a submodule CRC generator will be created.
    speed: USBSpeed
        USBSpeed signal or constant that specifies our speed in standalone mode.
    """

    _DATA_SUFFIX = 0b11

    def __init__(self, *, utmi, standalone=False, speed=None):

        self.utmi        = utmi
        self.standalone  = standalone
        self.speed       = speed

        #
        # I/O port
        #
        self.data_crc           = DataCRCInterface()
        self.timer              = InterpacketTimerInterface()
        self.stream             = USBOutStreamInterface()

        self.active_pid         = Signal(4)

        self.packet_complete    = Signal()
        self.ready_for_response = Signal()
        self.crc_mismatch       = Signal()
        self.packet_id          = Signal(4)


    def elaborate(self, platform):
        m = Module()

        # If we're in standalone mode, create our dependencies for us.
        if self.standalone:
            m.submodules.crc = crc = USBDataPacketCRC()
            crc.add_interface(self.data_crc)

            m.submodules.timer = timer = USBInterpacketTimer()
            timer.add_interface(self.timer)

            if not self.speed:
                self.speed = USBSpeed.FULL

            m.d.comb += [

                # Connect our CRC generator...
                crc.rx_data           .eq(self.utmi.rx_data),
                crc.rx_valid          .eq(self.utmi.rx_valid),
                crc.tx_valid          .eq(0),

                # ... and our timer.
                timer.speed           .eq(self.speed)
            ]


        # CRC-16 tracking signals.
        last_byte_crc = Signal(16)
        last_word_crc = Signal(16)

        # Keeps track of the most recently received word; for CRC comparison/removal.
        data_pipeline     = Signal(8 * 2)

        # Keep our control signals + strobes un-asserted unless otherwise specified.
        m.d.usb  += [
            self.packet_complete .eq(0),
            self.crc_mismatch    .eq(0),
        ]
        m.d.comb += [
            self.stream.next     .eq(0),
            self.data_crc.start  .eq(0),
        ]


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
                    is_data      = (self.utmi.rx_data[0:2] == self._DATA_SUFFIX)
                    is_valid_pid = (self.utmi.rx_data[0:4] == ~self.utmi.rx_data[4:8])

                    # If this is a data packet, capture its PID.
                    with m.If(is_valid_pid & is_data):
                        m.d.usb += self.active_pid.eq(self.utmi.rx_data),
                        m.next = "RECEIVE_FIRST_BYTE"

                    # Otherwise, ignore this packet.
                    with m.Else():
                        m.next = "IRRELEVANT"


            # RECEIVE_FIRST_BYTE -- capture the first byte into our pipeline.
            # We'll always pipeline two bytes before we start emitting; as we won't want to
            # pass through the last two bytes (the CRC).
            with m.State("RECEIVE_FIRST_BYTE"):

                with m.If(self.utmi.rx_valid):
                    m.d.usb += [
                        data_pipeline[8:]  .eq(self.utmi.rx_data),
                        last_byte_crc       .eq(self.data_crc.crc)
                    ]
                    m.next = 'RECEIVE_SECOND_BYTE'

                # If our packet stops before we see the first to bytes, we'll return to idle.
                # There's nothing to clean up, as we've never touched the stream.
                with m.If(~self.utmi.rx_active):
                    m.next = 'IDLE'


            # RECEIVE_SECOND_BYTE-- capture the second byte into our pipeline.
            with m.State("RECEIVE_SECOND_BYTE"):

                with m.If(self.utmi.rx_valid):
                    m.d.usb += [
                        data_pipeline[8:]   .eq(self.utmi.rx_data),
                        data_pipeline[0:8]  .eq(data_pipeline[8:]),

                        last_byte_crc       .eq(self.data_crc.crc),
                        last_word_crc       .eq(last_byte_crc),
                    ]
                    m.next = 'RECEIVE_AND_EMIT'

                # If our packet stops before we see the first to bytes, we'll return to idle.
                # There's nothing to clean up, as we've never touched the stream.
                with m.Elif(~self.utmi.rx_active):
                    m.next = 'IDLE'


            # RECEIVE_AND_EMIT -- receive bytes into our pipeline, and emit them.
            # Now that we have more than two bytes captured, we can start emitting bytes.
            # We'll always be emitting bytes that are two old -- so we can stop before our CRC.:
            with m.State("RECEIVE_AND_EMIT"):
                m.d.comb += self.stream.valid.eq(1)

                with m.If(self.utmi.rx_valid):

                    m.d.comb += [
                        # Emit the current packet...
                        self.stream.payload  .eq(data_pipeline[0:8]),
                        self.stream.next     .eq(1),
                    ]

                    m.d.usb += [

                        # ... capture the incoming one...
                        data_pipeline[8:]   .eq(self.utmi.rx_data),
                        data_pipeline[0:8]  .eq(data_pipeline[8:]),

                        # ... and update our cached CRCs.
                        last_byte_crc       .eq(self.data_crc.crc),
                        last_word_crc       .eq(last_byte_crc),
                    ]


                # Once we stop receiving data, check our CRC and finish.
                with m.If(~self.utmi.rx_active):

                    # If our CRC matches, this is a valid packet!
                    with m.If(last_word_crc == data_pipeline):

                        # Indicate so...
                        m.d.usb += [
                            self.packet_id       .eq(self.active_pid),
                            self.packet_complete .eq(1)
                        ]

                        # ... start counting our interpacket delay...
                        m.d.comb += [
                            self.timer.start  .eq(1)
                        ]

                        # ... and wait for it to complete.
                        m.next = 'INTERPACKET_DELAY'


                    # Otherwise, flag this as a CRC mismatch.
                    with m.Else():
                        m.d.usb += [
                            self.crc_mismatch    .eq(1)
                        ]

                        # ... and return to IDLE.
                        m.next = "IDLE"


            # INTERPACKET_DELAY -- we've received a valid packet; wait for an
            # interpacket delay before moving back to IDLE.
            with m.State("INTERPACKET_DELAY"):

                with m.If(self.timer.tx_allowed):
                    m.d.comb += self.ready_for_response.eq(1)
                    m.next = 'IDLE'


            # IRRELEVANT -- we've encountered a malformed or non-DATA packet.
            with m.State("IRRELEVANT"):

                with m.If(~self.utmi.rx_active):
                    m.next = "IDLE"

        return m


class USBDataPacketReceiverTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBDataPacketReceiver
    FRAGMENT_ARGUMENTS  = {'standalone': True}

    @usb_domain_test_case
    def test_data_receive(self):
        dut = self.dut
        stream = self.dut.stream


        #    0xC3,                                           # PID: Data
        #    0x00, 0x05, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, # DATA
        #    0xEB, 0xBC                                      # CRC

        # Before we send anything, our stream should be inactive.
        self.assertEqual((yield stream.valid), 0)

        # After sending our PID, we shouldn't see our stream be active.
        yield from self.start_packet()
        yield from self.provide_byte(0xc3)
        self.assertEqual((yield stream.valid), 0)

        # The stream shouldn't go valid for our first two data bytes, either.
        for b in [0x00, 0x05]:
            yield from self.provide_byte(b)
            self.assertEqual((yield stream.valid), 0)

        # Check that our active PID was successfully captured, and our current on
        # hasn't yet been updated.
        self.assertEqual((yield self.dut.active_pid), 3)
        self.assertEqual((yield self.dut.packet_id),  0)

        # The third byte should finally trigger our stream output...
        yield from self.provide_byte(0x08)
        self.assertEqual((yield stream.valid), 1)

        # ... and we should see the first byte on our stream.
        self.assertEqual((yield stream.next),       1)
        self.assertEqual((yield stream.payload), 0x00)

        # If we pause RxValid, we nothing should advance.
        yield self.utmi.rx_valid.eq(0)

        yield from self.provide_byte(0x08)
        self.assertEqual((yield stream.next),       0)
        self.assertEqual((yield stream.payload), 0x00)

        # Resuming should continue our advance...
        yield self.utmi.rx_valid.eq(1)

        # ... and we should process the remainder of the input
        for b in [0x00, 0x00, 0x00, 0x00, 0x00, 0xEB, 0xBC]:
            yield from self.provide_byte(b)

        # ... remaining two bytes behind.
        self.assertEqual((yield stream.next),       1)
        self.assertEqual((yield stream.payload), 0x00)


        # When we stop our packet, we should see our stream stop as well.
        # The last two bytes, our CRC, shouldn't be included.
        yield from self.end_packet()
        yield

        # And, since we sent a valid packet, we should see a pulse indicating the packet is valid.
        self.assertEqual((yield stream.valid),              0)
        self.assertEqual((yield self.dut.packet_complete),  1)

        # After an inter-packet delay, we should see that we're ready to respond.
        yield from self.advance_cycles(9)
        self.assertEqual((yield self.dut.ready_for_response), 0)


    @usb_domain_test_case
    def test_zlp(self):
        dut = self.dut
        stream = self.dut.stream

        #    0x4B        # DATA1
        #    0x00, 0x00  # CRC

        # Send our data PID.
        yield from self.start_packet()
        yield from self.provide_byte(0x4B)

        # Send our CRC.
        for b in [0x00, 0x00]:
            yield from self.provide_byte(b)
            self.assertEqual((yield stream.valid), 0)

        yield from self.end_packet()
        yield

        self.assertEqual((yield self.dut.packet_complete),  1)


class USBDataPacketDeserializer(Elaboratable):
    """ Gateware that captures USB data packet contents and parallelizes them.

    Attributes
    ----------
    data_crc: DataCRCInterface
        Connection to the CRC generator.

    new_packet: Signal(), output
        Strobe that pulses high for a single cycle when a new packet is delivered.
    packet_id: Signal(4), output
        The packet ID of the captured PID.

    packet: Signal(max_packet_size), output
        Packet data for a the most recently received packet.
    length: Signal(range(0, max_packet_length +1)), output
        The length of the packet data presented on the packet[] output.

    Parameters
    ----------
    utmi: UTMIInterface, or equivalent
        The UTMI bus to observe.
    max_packet_size: int
        The maximum packet (payload) size to be deserialized, in bytes.
    create_crc_generator: bool
        If True, a submodule CRC generator will be created. Excellent for testing.
    """

    _DATA_SUFFIX = 0b11

    def __init__(self, *, utmi, max_packet_size=64, create_crc_generator=False):

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
                    is_data      = (self.utmi.rx_data[0:2] == self._DATA_SUFFIX)
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

    Attributes
    ----------

    data_pid: Signal(2), input
        The data packet number to use. The potential PIDS are: 0 = DATA0, 1 = DATA1,
        2 = DATA2, 3 = MDATA; the interface is designed so that most endpoints can tie the MSb to
        zero and then perform PID toggling by toggling the LSb.

    crc: DataCRCInterface
        Interface to our data CRC generator.
    stream: USBInStreamInterface
        Stream input for the raw data to be transmitted.
    tx: UTMITransmitInterface
        UTMI-subset transmit interface

    Parameters
    ----------
    standalone: bool
        If True, this unit will include its internal CRC generator. Perfect for unit testing or debugging.
    """

    def __init__(self, standalone=False):

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

        # Stores the current data pid; latched in at the start of a transmission.
        current_data_pid = Signal(8)

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

                # Latch in the requested data PID.
                m.d.usb += current_data_pid.eq(data_pids[self.data_pid])

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
                    self.tx.data       .eq(current_data_pid),
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
                with m.If(self.tx.ready & (self.stream.last | ~self.stream.valid)):
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
                with m.If(self.tx.ready):
                    m.next = 'SEND_CRC_SECOND'


            # SEND_CRC_LAST -- send the last byte of the packet's CRC
            with m.State('SEND_CRC_SECOND'):

                # Send the relevant CRC byte...
                m.d.comb += [
                    self.tx.data       .eq(remaining_crc),
                    self.tx.valid      .eq(1),
                ]

                # ... and return to idle.
                with m.If(self.tx.ready):
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
    def test_single_byte(self):
        stream = self.dut.stream

        # Request single byte.
        yield stream.first.eq(1)
        yield stream.last.eq(1)
        yield stream.valid.eq(1)
        yield stream.payload.eq(0xAB)
        yield from self.wait_until(stream.ready)

        # Drop our last back to zero, immediately.
        yield stream.last.eq(0)
        yield stream.first.eq(0)
        yield stream.valid.eq(0)

        yield from self.advance_cycles(10)


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

    Attributes:

    issue_ack: Signal(), input
        Pulsed to generate an ACK handshake packet.
    issue_nak: Signal(), input
        Pulsed to generate a NAK handshake packet.
    issue_stall: Signal(), input
        Pulsed to generate a STALL handshake.

    tx: UTMITransmitInterface
        Interface to the relevant UTMI interface.
    """

    # Full contents of an ACK, NAK, and STALL packet.
    # These include the four check bits; which consist of the inverted PID.
    _PACKET_ACK   = 0b11010010
    _PACKET_NAK   = 0b01011010
    _PACKET_STALL = 0b00011110

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
                    m.d.usb += self.tx.data  .eq(self._PACKET_ACK),
                    m.next = 'TRANSMIT'

                with m.If(self.issue_nak):
                    m.d.usb += self.tx.data  .eq(self._PACKET_NAK),
                    m.next = 'TRANSMIT'

                with m.If(self.issue_stall):
                    m.d.usb += self.tx.data  .eq(self._PACKET_STALL),
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
        self.assertEqual((yield dut.tx.data), USBHandshakeGenerator._PACKET_ACK)

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
        self.assertEqual((yield dut.tx.data), USBHandshakeGenerator._PACKET_ACK)

        # ... our transmit request should be valid...
        self.assertEqual((yield dut.tx.valid), 1)

        # ... and then drop out of being valid after one cycle.
        yield
        self.assertEqual((yield dut.tx.valid), 0)



class USBInterpacketTimer(Elaboratable):
    """ Module that tracks inter-packet timings, enforcing spec-mandated packet gaps.

    Ports other than :attr:`speed` are added dynamically via :method:add_interface`.

    Attributes
    ----------
    speed: Signal(2), input
        The device's current operating speed. Should be a USBSpeed enumeration value --
        0 for high, 1 for full, 2 for low.

    """

    # Per the USB 2.0 and ULPI 1.1 specifications, after receipt:
    #   - A FS/LS device needs to wait 2 bit periods before transmitting; and must
    #     respond before 6.5 bit times pass. [USB2, 7.1.18.1]
    #   - Two FS bit periods is equivalent to 10 ULPI clocks, and two LS periods is
    #     equivalent to 80 ULPI clocks. 6.5 FS bit periods is equivalent to 32 ULPI clocks,
    #     and 6.5 LS bit periods is equivalent to 260 ULPI clocks. [ULPI 1.1, Figure 18].
    #   - A HS device needs to wait 8 HS bit periods before transmitting [USB2, 7.1.18.2].
    #     Each ULPI cycle is 8 HS bit periods, so we'll only need to wait one cycle.
    _HS_RX_TO_TX_DELAY     = {60e6: (  1,  24)}
    _FS_RX_TO_TX_DELAY     = {60e6: ( 10,  32), 12e6: (2, 7)}
    _LS_RX_TO_TX_DELAY     = {60e6: ( 80, 260)}

    # Per the USB 2.0 and ULPI 1.1 specifications, after transission:
    #   - A FS/LS can assume it won't receive a response after 16 bit times [USB2, 7.1.18.1].
    #     This is equivalent to 80 ULPI clocks (FS), or 640 ULPI clocks (LS).
    #   - A HS device can assume it won't receive a response after 736 bit times.
    #     This is equivalent to 92 ULPI clocks.
    _HS_TX_TO_RX_TIMEOUT = {60e6:  92}
    _FS_TX_TO_RX_TIMEOUT = {60e6:  80, 12e6: 16}
    _LS_TX_TO_RX_TIMEOUT = {60e6: 640}


    def __init__(self, domain_clock=60e6, fs_only=False):
        self._fs_only = fs_only

        # Start off with empty delays -- this doesn't change anything, but makes
        # linters happy. :)
        self._hs_rx_to_tx_delay   = None
        self._ls_rx_to_tx_delay   = None
        self._hs_rx_to_tx_timeout = None
        self._ls_rx_to_tx_timeout = None

        # Validate that we have a usable FS Rx/Tx delay.
        if domain_clock not in self._FS_RX_TO_TX_DELAY:
            raise ValueError(f"Domain clock must be in {self._FS_TX_TO_RX_TIMEOUT.keys()}, not {domain_clock}.")

        # Capture our FS delay for the current clock speed.
        self._fs_rx_to_tx_delay   = self._FS_RX_TO_TX_DELAY[domain_clock]
        self._fs_tx_to_rx_timeout = self._FS_TX_TO_RX_TIMEOUT[domain_clock]
        self._counter_max = self._FS_TX_TO_RX_TIMEOUT[domain_clock]

        # If we're not in a FS-only configuration, capture our other delays.
        if not self._fs_only:
            if domain_clock not in self._HS_RX_TO_TX_DELAY:
                raise ValueError(f"Domain clock must be in {self._FS_TX_TO_RX_TIMEOUT.keys()}, not {domain_clock}.")

            # Capute our HS and LS delays for the given clock speed.
            self._hs_rx_to_tx_delay   = self._HS_RX_TO_TX_DELAY[domain_clock]
            self._ls_rx_to_tx_delay   = self._LS_RX_TO_TX_DELAY[domain_clock]
            self._hs_tx_to_rx_timeout = self._HS_TX_TO_RX_TIMEOUT[domain_clock]
            self._ls_tx_to_rx_timeout = self._LS_TX_TO_RX_TIMEOUT[domain_clock]
            self._counter_max         = self._LS_TX_TO_RX_TIMEOUT[domain_clock]



        # List of interfaces to users of this module.
        self._interfaces               = []

        #
        # I/O port
        #
        self.speed = Signal(2)


    def add_interface(self, interface: InterpacketTimerInterface):
        """ Adds a connection to a user of this module.

        This module performs no multiplexing; it's assumed only one interface will be active at a time.

        Parameters
        ---------
        interface: InterpacketTimerInterface
            The InterPacketTimer interface to add to our module.
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
        counter = Signal(range(0, self._counter_max + 2))

        # Reset our timer whenever any of our interfaces request a timer start.
        reset_signals = (interface.start for interface in self._interfaces)
        any_reset = functools.reduce(operator.__or__, reset_signals)

        # When a reset is requested, start the counter from 0.
        with m.If(any_reset):
            m.d.usb += counter.eq(0)
        with m.Elif(counter < self._counter_max + 1):
            m.d.usb += counter.eq(counter + 1)

        #
        # Create our counter-progress strobes.
        # This could be made less repetitive, but spreading it out here
        # makes the documentation above clearer.
        #
        with m.If(self.speed == USBSpeed.HIGH):
            if not self._fs_only:
                m.d.comb += [
                    rx_to_tx_at_min   .eq(counter == self._hs_rx_to_tx_delay[0]),
                    rx_to_tx_at_max   .eq(counter == self._hs_rx_to_tx_delay[1]),
                    tx_to_rx_timeout  .eq(counter == self._hs_tx_to_rx_timeout)
                ]
        with m.Elif(self.speed == USBSpeed.FULL):
            m.d.comb += [
                rx_to_tx_at_min   .eq(counter == self._fs_rx_to_tx_delay[0]),
                rx_to_tx_at_max   .eq(counter == self._fs_rx_to_tx_delay[1]),
                tx_to_rx_timeout  .eq(counter == self._fs_tx_to_rx_timeout)
            ]
        with m.Else():
            if not self._fs_only:
                m.d.comb += [
                    rx_to_tx_at_min   .eq(counter == self._hs_rx_to_tx_delay[0]),
                    rx_to_tx_at_max   .eq(counter == self._hs_rx_to_tx_delay[1]),
                    tx_to_rx_timeout  .eq(counter == self._hs_tx_to_rx_timeout)
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
