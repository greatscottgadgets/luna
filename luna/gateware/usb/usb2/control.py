#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Low-level USB transciever gateware -- control transfer components. """

import unittest

from amaranth              import Signal, Module, Elaboratable
from usb_protocol.emitters import DeviceDescriptorCollection
from usb_protocol.types    import USBRequestType

from .packet               import DataCRCInterface, USBDataPacketCRC, USBInterpacketTimer
from .packet               import USBTokenDetector, TokenDetectorInterface
from .packet               import InterpacketTimerInterface, HandshakeExchangeInterface
from .endpoint             import EndpointInterface
from .request              import USBSetupDecoder, USBRequestHandlerMultiplexer, StallOnlyRequestHandler
from ..request.standard    import StandardRequestHandler
from ..stream              import USBInStreamInterface, USBOutStreamInterface


class USBControlEndpoint(Elaboratable):
    """ Gateware that manages control request data progression.

    This class is used by creating one or more *request handler* modules; which define how requests
    are handled. These handlers can be bound using :attr:`add_request_handler`.

    For convenience, this module can also automatically be populated with a ``StandardRequestHandler``
    via the :attr:`add_standard_request_handlers`.

    Attributes
    ----------
    interface: EndpointInterface
        The interface from this endpoint to the core device hardware.

    Parameters
    ----------
        utmi: UTMI bus, or equivalent translator
            The UTMI bus we'll monitor for data. We'll consider this read-only.
        endpoint_number: int, optional
            The endpoint number for this control interface; defaults to (and almost always should
            be) zero.
        standalone: bool
            Debug parameter. If true, this module will operate without external components;
            i.e. without an internal data-CRC generator, or tokenizer. In this case, tokenizer
            and timer should be set to None; and will be ignored.
    """

    def __init__(self, *, utmi, endpoint_number=0, standalone=False, max_packet_size=64):
        self.utmi             = utmi
        self._standalone      = standalone
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size

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


    def add_standard_request_handlers(self, descriptors: DeviceDescriptorCollection, **kwargs):
        """ Adds a handlers for the standard USB requests.

        This will handle all Standard-type requests; so any additional request handlers
        must not handle Standard requests.

        Parameters will be passed on to StandardRequestHandler.
        """
        handler = StandardRequestHandler(descriptors, max_packet_size=self._max_packet_size, **kwargs)
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

        if self._standalone:

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
            # Per [USB2.0: 8.5.3], the first packet of the DATA or STATUS phase always carries a DATA1 PID.
            interface.tx_pid_toggle                .eq(request_handler.tx_data_pid)
        ]


        #
        # Core control request handler.
        # Behavior dictated by [USB2, 8.5.3].
        #
        endpoint_targeted = (self.interface.tokenizer.endpoint == self._endpoint_number)
        with m.FSM(domain="usb"):

            # SETUP -- The "SETUP" phase of a control request. We'll wait here
            # until the SetupDetector detects a valid setup packet for us.
            with m.State('SETUP'):

                # We won't do anything until we receive a SETUP token.
                with m.If(setup_decoder.packet.received & endpoint_targeted):

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
                        # If we don't have a data phase, our status phase is always an IN [USB2.0: 8.5.3]
                        m.next = 'STATUS_IN'


            with m.State('DATA_IN'):
                self._handle_setup_reset(m)

                # Wait until we have an IN token, and are allowed to respond to it.
                allowed_to_respond = interface.tokenizer.ready_for_response & endpoint_targeted
                with m.If(allowed_to_respond & interface.tokenizer.is_in):

                    # Notify the request handler to prepare a response.
                    m.d.comb += request_handler.data_requested.eq(1)

                # Once we get an OUT token, we should move on to the STATUS stage. [USB2, 8.5.3]
                with m.If(endpoint_targeted & interface.tokenizer.new_token & (interface.tokenizer.is_out | interface.tokenizer.is_ping)):
                    m.next = 'STATUS_OUT'


            with m.State('DATA_OUT'):
                self._handle_setup_reset(m)

                # Pass through our Rx related signals iff we're in the DATA_OUT stage,
                # and the most recent token pointed to our endpoint. This ensures the
                # request handler only ever sees data events related to it; this simplifies
                # the request handler logic significantly.
                with m.If(endpoint_targeted & interface.tokenizer.is_out):
                    m.d.comb += [
                        interface.rx                           .connect(request_handler.rx),
                        request_handler.rx_ready_for_response  .eq(interface.rx_ready_for_response)
                    ]

                # Once we get an IN token, we should move on to the STATUS stage. [USB2, 8.5.3]
                with m.If(endpoint_targeted & interface.tokenizer.new_token & interface.tokenizer.is_in):
                    m.next = 'STATUS_IN'

                # Respond to PING token [USB2.0: 8.5.1]
                with m.If(endpoint_targeted & interface.tokenizer.ready_for_response & interface.tokenizer.is_ping):
                    m.d.comb += interface.handshakes_out.ack.eq(1)


            # STATUS_IN -- We're currently in the status stage, and we're expecting an IN token.
            # We'll wait for that token.
            with m.State('STATUS_IN'):
                self._handle_setup_reset(m)

                # If we respond to a status-phase IN token, we'll always use a DATA1 PID [USB2.0: 8.5.3]

                # When we get an IN token, the host is looking for a status-stage ZLP.
                # Notify the target handler.
                allowed_to_respond = interface.tokenizer.ready_for_response & endpoint_targeted
                with m.If(allowed_to_respond & interface.tokenizer.is_in):
                    m.d.comb += request_handler.status_requested.eq(1)


            # STATUS_OUT -- We're currently in the status stage, and we're expecting the DATA packet for
            # an OUT request.
            with m.State('STATUS_OUT'):
                self._handle_setup_reset(m)

                # Once we've received a new DATA packet, we're ready to handle a status request.
                allowed_to_respond = interface.rx_ready_for_response & endpoint_targeted
                with m.If(allowed_to_respond & interface.tokenizer.is_out):
                    m.d.comb += request_handler.status_requested.eq(1)

                # Respond to PING token [USB2.0: 8.5.1]
                with m.If(endpoint_targeted & interface.tokenizer.ready_for_response & interface.tokenizer.is_ping):
                    m.d.comb += interface.handshakes_out.ack.eq(1)

        return m


if __name__ == "__main__":
    unittest.main()
