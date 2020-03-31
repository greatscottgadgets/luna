#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- control transfer components. """

import unittest

from nmigen            import Signal, Module, Elaboratable
from ...test           import usb_domain_test_case

from .packet           import DataCRCInterface, USBDataPacketCRC, USBInterpacketTimer
from .packet           import USBTokenDetector, USBPacketizerTest, TokenDetectorInterface
from .packet           import InterpacketTimerInterface, HandshakeExchangeInterface
from .request          import USBSetupDecoder, StandardRequestHandler
from ...interface      import USBInStreamInterface


class USBControlEndpoint(Elaboratable):
    """ Base class for USB control endpoint implementers.

    I/O port:
        *: data_crc            -- Control connection for our data-CRC unit.
        *: timer               -- Interface to our interpacket timer.
        I: tokenizer           -- Interface to our TokenDetector; notifies us of USB tokens.

        # Device state.
        I: speed               -- The device's current operating speed. Should be a USBSpeed
                                  enumeration value -- 0 for high, 1 for full, 2 for low.

        # Address / configuration connections.
        O: address_changed     -- Strobe; pulses high when the device's address should be changed.
        O: new_address[7]      -- When `address_changed` is high, this field contains the address that
                                  should be adopted.

        # Data/handshake connections.
        *: tx                  -- Transmit interface for this endpoint.
        O: tx_pid_toggle       -- Value for the data PID toggle; 0 indicates we'll send DATA0; 1 indicates DATA1.

        *: handshakes_detected -- Carries handshakes detected from the host.
        O: issue_ack           -- Strobe; pulses high when the endpoint wants to issue an ACK handshake.
        O: issue_nak           -- Strobe; pulses high when the endpoint wants to issue a  NAK handshake.
        O: issue_stall         -- Strobe; pulses high when the endpoint wants to issue a  STALL handshake.

        # Diagnostic I/O.
        last_request[8] -- Request number of the last request.
    """

    def __init__(self, *, utmi, standalone=False):
        """
        Parameters:
            utmi       -- The UTMI bus we'll monitor for data. We'll consider this read-only.

            standalone     -- Debug parameter. If true, this module will operate without external components;
                              i.e. without an internal data-CRC generator, or tokenizer. In this case, tokenizer
                              and timer should be set to None; and will be ignored.
        """
        self.utmi                = utmi
        self.standalone          = standalone

        #
        # I/O Port
        #
        self.data_crc            = DataCRCInterface()
        self.tokenizer           = TokenDetectorInterface()
        self.timer               = InterpacketTimerInterface()

        self.speed               = Signal(2)

        self.address_changed     = Signal()
        self.new_address         = Signal(7)

        self.tx                  = USBInStreamInterface()
        self.tx_pid_toggle       = Signal()
        self.handshakes_detected = HandshakeExchangeInterface(is_detector=True)

        self.issue_ack           = Signal()
        self.issue_nak           = Signal()
        self.issue_stall         = Signal()

        # Debug outputs
        self.last_request        = Signal(8)
        self.new_packet          = Signal()



    def elaborate(self, platform):
        m = Module()

        #
        # Test scaffolding.
        #

        if self.standalone:

            # Create our timer...
            m.submodules.timer = timer = USBInterpacketTimer()
            timer.add_interface(self.timer)

            # ... our CRC generator ...
            m.submodules.crc = crc = USBDataPacketCRC()
            crc.add_interface(self.data_crc)
            m.d.comb += [
                crc.rx_data    .eq(self.utmi.rx_data),
                crc.rx_valid   .eq(self.utmi.rx_valid),
                crc.tx_valid   .eq(0)
            ]

            # ... and our tokenizer.
            m.submodules.token_detector = tokenizer = USBTokenDetector(utmi=self.utmi)
            m.d.comb += tokenizer.interface.connect(self.tokenizer)

        #
        # Submodules
        #

        # Create a start signal for our inter-packet timer.
        interpacket_timer_start = Signal()

        # Create our SETUP packet decoder.
        m.submodules.setup_decoder = setup_decoder = USBSetupDecoder(utmi=self.utmi)
        m.d.comb += [
            self.data_crc       .connect(setup_decoder.data_crc),
            self.tokenizer      .connect(setup_decoder.tokenizer),
            setup_decoder.speed .eq(self.speed),

            # And attach our timer interface to both our local users and
            # to our setup decoder.
            self.timer          .attach(setup_decoder.timer, interpacket_timer_start)

        ]

        # Automatically acknowledge any valid SETUP packet.
        m.d.comb += self.issue_ack.eq(setup_decoder.ack)

        # Debug output.
        m.d.comb += [
            self.last_request  .eq(setup_decoder.packet.request),
            self.new_packet    .eq(setup_decoder.packet.received),
        ]


        #
        # Request handler logic
        #

        # TODO: Implement an .add_request_handlers() function
        m.submodules.request_handler = request_handler = StandardRequestHandler()
        handler = request_handler.interface

        m.d.comb += [
            setup_decoder.packet        .connect(handler.setup),
            self.handshakes_detected    .connect(handler.handshake_detected),

            # TODO: connect these via a mux/arbitrator.
            self.tx                     .connect(handler.tx),
            self.issue_stall            .eq(handler.handshake.stall),

            self.address_changed        .eq(handler.address_changed),
            self.new_address            .eq(handler.new_address),
        ]


        #
        # Core control request handler.
        # Behavior dictated by [USB2, 8.5.3].
        #
        with m.FSM(domain="usb"):

            # SETUP -- The "SETUP" phase of a control request. We'll wait here
            # until the SetupDetector detects a valid setup packet for us.
            with m.State('SETUP'):

                # We won't do anything until we receive a SETUP token.
                with m.If(setup_decoder.packet.received):

                    # If our SETUP packet indicates we'll have a data stage,
                    # move to the DATA stage. Otherwise, move directly to the
                    # status stage.
                    with m.If(setup_decoder.packet.length):
                        m.next = 'DATA'
                    with m.Else():
                        m.next = 'STATUS'


            with m.State('DATA'):

                # Once our interpacket delay is complete, we'll need to respond.
                with m.If(self.tokenizer.ready_for_response):
                    m.d.comb += request_handler.interface.data_requested.eq(1)

                    # FIXME: correct packet ordering
                    m.next = 'SETUP'


            # STATUS -- We're currently in the status stage. We'll wait for an IN or OUT, and then
            # prompt our request handler to report the status of our transaction.
            with m.State('STATUS'):

                # If we respond to a status-phase IN token, we'll always use a DATA1 PID [USB2 8.5.3]
                m.d.usb += self.tx_pid_toggle.eq(1)

                # Once our interpacket delay is complete, we'll prompt the request handler for a response.
                with m.If(self.tokenizer.ready_for_response):
                    m.d.comb += request_handler.interface.status_requested.eq(1)
                    m.next = 'SETUP'


        return m



class USBControlEndpointTest(USBPacketizerTest):
    FRAGMENT_UNDER_TEST = USBControlEndpoint
    FRAGMENT_ARGUMENTS = {'standalone': True}

    @usb_domain_test_case
    def test_automatic_nak(self):

        # Provide our setup packet.
        yield from self.provide_packet(
            0b00101101, # PID: SETUP token.
            0b00000000, 0b00010000 # Address 0, endpoint 0, CRC
        )

        # Provide our data packet, which has this as a SET_ADDRESS out request with no data.
        yield from self.provide_packet(
            0xC3, #PID: DATA0
            0x00, 0x05, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00,
            0xEA, 0xC7
        )

        # FIXME: assert here
        yield from self.advance_cycles(20)

        # Provide our status stage token.
        yield from self.provide_packet(
            0b01101001, # PID: IN token.
            0b00000000, 0b00010000 # Address 0, endpoint 0, CRC
        )

        yield from self.advance_cycles(20)




if __name__ == "__main__":
    unittest.main()
