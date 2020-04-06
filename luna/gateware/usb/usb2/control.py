#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- control transfer components. """

import unittest

from nmigen                import Signal, Module, Elaboratable
from usb_protocol.emitters import DeviceDescriptorCollection
from usb_protocol.types    import USBRequestType

from .packet               import DataCRCInterface, USBDataPacketCRC, USBInterpacketTimer
from .packet               import USBTokenDetector, TokenDetectorInterface
from .packet               import InterpacketTimerInterface, HandshakeExchangeInterface
from .endpoint             import EndpointInterface
from .request              import USBSetupDecoder, USBRequestHandlerMultiplexer, StallOnlyRequestHandler
from ..request.standard    import StandardRequestHandler
from ..stream              import USBInStreamInterface, USBOutStreamInterface


# TODO: rename this to indicate that it's a gateware control endpoint

class USBControlEndpoint(Elaboratable):
    """ Base class for USB control endpoint implementers.

    I/O port:
        *: data_crc               -- Control connection for our data-CRC unit.
        *: timer                  -- Interface to our interpacket timer.
        *: tokenizer              -- Interface to our TokenDetector; notifies us of USB tokens.

        # Device state.
        I: speed                  -- The device's current operating speed. Should be a USBSpeed
                                     enumeration value -- 0 for high, 1 for full, 2 for low.

        # Address / configuration connections.
        O: address_changed        -- Strobe; pulses high when the device's address should be changed.
        O: new_address[7]         -- When `address_changed` is high, this field contains the address that
                                     should be adopted.

        I: active_config          -- The configuration number of the active configuration.
        O: config_changed         -- Strobe; pulses high when the device's configuration should be changed.
        O: new_config[8]          -- When `config_changed` is high, this field contains the configuration that
                                     should be applied.

        # Data/handshake connections.
        *  rx                     -- Receive interface for this endpoint.
        I: rx_complete            -- Strobe that indicates that the concluding rx-stream was valid (CRC check passed).
        I  rx_ready_for_response  -- Strobe that indicates that we're ready to respond to a complete transmission.
                                     Indicates that an interpacket delay has passed after an `rx_complete` strobe.
        I: rx_invalid             -- Strobe that indicates that the concluding rx-stream was invalid (CRC check failed).

        *: tx                     -- Transmit interface for this endpoint.
        O: tx_pid_toggle          -- Value for the data PID toggle; 0 indicates we'll send DATA0; 1 indicates DATA1.

        *: handshakes_detected    -- Carries handshakes detected from the host.
        O: issue_ack              -- Strobe; pulses high when the endpoint wants to issue an ACK handshake.
        O: issue_nak              -- Strobe; pulses high when the endpoint wants to issue a  NAK handshake.
        O: issue_stall            -- Strobe; pulses high when the endpoint wants to issue a  STALL handshake.
    """

    def __init__(self, *, utmi, standalone=False):
        """
        Parameters:
            utmi       -- The UTMI bus we'll monitor for data. We'll consider this read-only.

            standalone     -- Debug parameter. If true, this module will operate without external components;
                              i.e. without an internal data-CRC generator, or tokenizer. In this case, tokenizer
                              and timer should be set to None; and will be ignored.
        """
        self.utmi       = utmi
        self.standalone = standalone

        #
        # I/O Port
        #
        self.interface = EndpointInterface()

        #
        # Internals.
        #

        # List of the modules that will handle control requests.
        self._request_handlers = []


    def add_request_handler(self, request_handler):
        """ Adds a ControlRequestHandler module to this control endpoint.

        No arbitration is performed between request handlers; so it's important
        that request handlers not overlap in the requests they handle.
        """
        self._request_handlers.append(request_handler)


    def add_standard_request_handlers(self, descriptors: DeviceDescriptorCollection):
        """ Adds a handlers for the standard USB requests.

        This will handle all Standard-type requests; so any additional request handlers
        must not handle Standard requests.

        Parameters:

        """
        handler = StandardRequestHandler(descriptors)
        self._request_handlers.append(handler)


    def _handle_setup_reset(self, m):
        """ Adds a FSM condition that moves back to the SETUP phase if we ever receive a setup token.

        Should only be used within our core FSM.
        """
        tokenizer = self.interface.tokenizer

        # If we receive a SETUP token, always move back to the SETUP stage.
        with m.If(tokenizer.new_token & tokenizer.is_setup):
            m.next = 'SETUP'


    def elaborate(self, platform):
        m = Module()
        interface = self.interface

        #
        # Test scaffolding.
        #

        if self.standalone:

            # Create our timer...
            m.submodules.timer = timer = USBInterpacketTimer()
            timer.add_interface(interface.timer)

            # ... our CRC generator ...
            m.submodules.crc = crc = USBDataPacketCRC()
            crc.add_interface(interface.data_crc)
            m.d.comb += [
                crc.rx_data    .eq(self.utmi.rx_data),
                crc.rx_valid   .eq(self.utmi.rx_valid),
                crc.tx_valid   .eq(0)
            ]

            # ... and our tokenizer.
            m.submodules.token_detector = tokenizer = USBTokenDetector(utmi=self.utmi)
            m.d.comb += tokenizer.interface.connect(interface.tokenizer)


        #
        # Convenience feature:
        #
        # If we have -only- a standard request handler, automatically add a handler that will
        # stall all other requests.
        #
        single_handler = (len(self._request_handlers) == 1)
        if (single_handler and isinstance(self._request_handlers[0], StandardRequestHandler)):

            # Add a handler that will stall any non-standard request.
            stall_condition = lambda setup : setup.type != USBRequestType.STANDARD
            self.add_request_handler(StallOnlyRequestHandler(stall_condition))


        #
        # Submodules
        #

        # Create our SETUP packet decoder.
        m.submodules.setup_decoder = setup_decoder = USBSetupDecoder(utmi=self.utmi)
        m.d.comb += [
            interface.data_crc   .connect(setup_decoder.data_crc),
            interface.tokenizer  .connect(setup_decoder.tokenizer),
            setup_decoder.speed  .eq(interface.speed),

            # And attach our timer interface to both our local users and
            # to our setup decoder.
            interface.timer      .attach(setup_decoder.timer)

        ]


        #
        # Request handler logic.
        #

        # Multiplex the output of each of our request handlers.
        m.submodules.request_mux = request_mux = USBRequestHandlerMultiplexer()
        request_handler = request_mux.shared

        # Add each of our handlers to the endpoint; and add it to our mux.
        for handler in self._request_handlers:

            # Create a display name for the handler...
            name = handler.__class__.__name__
            if hasattr(m.submodules, name):
                name = f"{name}_{id(handler)}"

            # ... and add it.
            m.submodules[name] = handler
            request_mux.add_interface(handler.interface)


        # ... and hook it up.
        m.d.comb += [
            setup_decoder.packet                   .connect(request_handler.setup),
            interface.tokenizer                    .connect(request_handler.tokenizer),

            request_handler.tx                     .attach(interface.tx),
            interface.handshakes_out.ack           .eq(setup_decoder.ack | request_handler.handshakes_out.ack),
            interface.handshakes_out.nak           .eq(request_handler.handshakes_out.nak),
            interface.handshakes_out.stall         .eq(request_handler.handshakes_out.stall),
            interface.handshakes_in                .connect(request_handler.handshakes_in),

            interface.address_changed              .eq(request_handler.address_changed),
            interface.new_address                  .eq(request_handler.new_address),

            request_handler.active_config          .eq(interface.active_config),
            interface.config_changed               .eq(request_handler.config_changed),
            interface.new_config                   .eq(request_handler.new_config),

            # Fix our data PIDs to DATA1, for now, as we don't support multi-packet responses, yet.
            # Per [USB2 8.5.3], the first packet of the DATA or STATUS phase always carries a DATA1 PID.
            interface.tx_pid_toggle.eq(1)
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

                    # If our SETUP packet indicates we'll have a data stage (wLength > 0)
                    # move to the DATA stage. Otherwise, move directly to the status stage [8.5.3].
                    with m.If(setup_decoder.packet.length):

                        # If this is an device -> host request, expect an IN packet.
                        with m.If(setup_decoder.packet.is_in_request):
                            m.next = 'DATA_IN'

                        # Otherwise, expect an OUT one.
                        with m.Else():
                            m.next = 'DATA_OUT'

                    with m.Else():
                        # If we don't have a data phase, our status phase is always an IN [USB2 8.5.3]
                        m.next = 'STATUS_IN'


            with m.State('DATA_IN'):
                self._handle_setup_reset(m)

                # Wait until we have an IN token, and are allowed to respond to it.
                with m.If(interface.tokenizer.ready_for_response & interface.tokenizer.is_in):

                    # Notify the request handler to prepare a response.
                    m.d.comb += request_handler.data_requested.eq(1)

                # Once we get an OUT token, we should move on to the STATUS stage. [USB2, 8.5.3]
                with m.If(interface.tokenizer.new_token & interface.tokenizer.is_out):
                    m.next = 'STATUS_OUT'


            with m.State('DATA_OUT'):
                self._handle_setup_reset(m)

                # Pass through our Rx related signals iff we're in the DATA_OUT stage,
                # and the most recent token pointed to our endpoint. This ensures the
                # request handler only ever sees data events related to it; this simplifies
                # the request handler logic significantly.
                with m.If((interface.tokenizer.endpoint == 0) & interface.tokenizer.is_out):
                    m.d.comb += [
                        interface.rx                           .connect(request_handler.rx),
                        request_handler.rx_ready_for_response  .eq(interface.rx_ready_for_response)
                    ]

                # Once we get an IN token, we should move on to the STATUS stage. [USB2, 8.5.3]
                with m.If(interface.tokenizer.new_token & interface.tokenizer.is_in):
                    m.next = 'STATUS_IN'


            # STATUS_IN -- We're currently in the status stage, and we're expecting an IN token.
            # We'll wait for that token.
            with m.State('STATUS_IN'):
                self._handle_setup_reset(m)

                # If we respond to a status-phase IN token, we'll always use a DATA1 PID [USB2 8.5.3]

                # When we get an IN token, the host is looking for a status-stage ZLP.
                # Notify the target handler.
                with m.If(interface.tokenizer.ready_for_response & interface.tokenizer.is_in):
                    m.d.comb += request_handler.status_requested.eq(1)


            # STATUS_OUT -- We're currently in the status stage, and we're expecting the DATA packet for
            # an OUT request.
            with m.State('STATUS_OUT'):
                self._handle_setup_reset(m)

                # Once we've received a new DATA packet, we're ready to handle a status request.
                with m.If(interface.rx_ready_for_response & interface.tokenizer.is_out):
                    m.d.comb += request_handler.status_requested.eq(1)

        return m


if __name__ == "__main__":
    unittest.main()
