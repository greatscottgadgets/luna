#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Low-level USB3 transciever gateware -- control transfer components. """

from nmigen import *

from ..protocol.endpoint      import SuperSpeedEndpointInterface
from usb_protocol.emitters    import DeviceDescriptorCollection
from usb_protocol.types       import USBRequestType

from ..application.request    import SuperSpeedRequestHandlerInterface, SuperSpeedSetupDecoder
from ..request.standard       import StandardRequestHandler


class USB3ControlEndpoint(Elaboratable):
    """ Gateware that manages control request data progression.

    This class is used by creating one or more *request handler* modules; which define how requests
    are handled. These handlers can be bound using :attr:`add_request_handler`.

    For convenience, this module can also automatically be populated with a ``StandardRequestHandler``
    via the :attr:`add_standard_request_handlers`.

    Attributes
    ----------
    interface: SuperSpeedEndpointInterface
        The interface from this endpoint to the core device hardware.

    Parameters
    ----------
        endpoint_number: int, optional
            The endpoint number for this control interface; defaults to (and almost always should
            be) zero.
    """

    def __init__(self, *, endpoint_number=0, descriptors=None):
        self._endpoint_number = endpoint_number
        self._descriptors     = descriptors

        # List of the modules that will handle control requests.
        self._request_handlers = []

        #
        # I/O Port
        #
        self.interface = SuperSpeedEndpointInterface()



    def add_request_handler(self, request_handler):
        """ Adds a ControlRequestHandler module to this control endpoint.

        No arbitration is performed between request handlers; so it's important
        that request handlers not overlap in the requests they handle.
        """
        self._request_handlers.append(request_handler)



    def elaborate(self, platform):
        m = Module()

        # Shortcuts.
        interface      = self.interface
        handshakes_out = self.interface.handshakes_out
        handshakes_in  = self.interface.handshakes_in


        #
        # Setup packet decoder.
        #
        m.submodules.setup_decoder = setup_decoder = SuperSpeedSetupDecoder()
        m.d.comb += [
            setup_decoder.sink       .tap(interface.rx),
            setup_decoder.header_in  .eq(interface.rx_header),

            setup_decoder.rx_good    .eq(interface.rx_complete),
            setup_decoder.rx_bad     .eq(interface.rx_invalid),
        ]


        #
        # Request handler interfacing.
        #

        # TODO: move this to a helper function
        m.submodules.handlers = request_handlers = StandardRequestHandler(self._descriptors)

        # TODO: add in a request handler multiplexer, so we can support multiple request handlers
        request_interface = request_handlers.interface

        m.d.comb += [

            # Receive.
            request_interface.rx          .tap(interface.rx),

            # Transmit.
            interface.tx                  .stream_eq(request_interface.tx),
            interface.tx_length           .eq(request_interface.tx_length),
            interface.tx_sequence_number  .eq(0),
            interface.tx_endpoint_number  .eq(self._endpoint_number),

            # Status.
            interface.handshakes_in       .connect(request_interface.handshakes_in),
            interface.handshakes_out      .connect(request_interface.handshakes_out),

            # Address / config management.
            interface.address_changed     .eq(request_interface.address_changed),
            interface.new_address         .eq(request_interface.new_address),

            interface.config_changed      .eq(request_interface.config_changed),
            interface.new_config          .eq(request_interface.new_config),

        ]

        #
        # Data sequence handling.
        #

        # As we handle our requests, we're required to set: [USB3.2r1: 8.12.2]
        # - Sequence Number to 1 in the SETUP stage, indicating that we can accept a data stage if one follows.
        # - Sequence Number to 1 in the ACK stage.
        # - NumP to 1, indicating that we're accepting the control transaction now
        #   (If we set NumP to 0; this "pauses" the transaction until we send ERDY.)
        m.d.comb += handshakes_out.next_sequence.eq(1),

        #
        # SETUP stage handling.
        #

        # Our setup stage is easy: we just pass through our setup packet through to the request handlers...
        m.d.comb += request_interface.setup  .eq(setup_decoder.packet)

        # ... and then ACK any SETUP packet that comes through, as we're required to [USB3.2r1: 8.12.2].
        with m.If(setup_decoder.packet.received):
            m.d.comb += [
                handshakes_out.endpoint_number  .eq(self._endpoint_number),

                handshakes_out.retry_required   .eq(0),

                handshakes_out.send_ack         .eq(1)
            ]


        #
        # DATA stage handling.
        #
        is_to_us    = (handshakes_in.endpoint_number == self._endpoint_number)
        is_in_token = (handshakes_in.number_of_packets != 0)

        # Pass through any IN tokens as data requests to our request handlers.
        with m.If(handshakes_in.ack_received & is_to_us & is_in_token):
            m.d.comb += request_interface.data_requested.eq(1)


        #
        # STATUS stage handling.
        #
        with m.If(handshakes_in.status_received):
            m.d.comb += request_interface.status_requested.eq(1)

        return m
