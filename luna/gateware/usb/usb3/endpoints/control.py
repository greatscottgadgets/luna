#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Low-level USB3 transciever gateware -- control transfer components. """

from amaranth import *

from usb_protocol.emitters    import DeviceDescriptorCollection
from usb_protocol.types       import USBRequestType, USBDirection

from ..protocol.endpoint      import SuperSpeedEndpointInterface
from ..application.request    import SuperSpeedRequestHandlerInterface, SuperSpeedSetupDecoder
from ..application.request    import SuperSpeedRequestHandlerMultiplexer, StallOnlyRequestHandler
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

    def __init__(self, *, endpoint_number=0):
        self._endpoint_number = endpoint_number

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


    def add_standard_request_handlers(self, descriptors: DeviceDescriptorCollection):
        """ Adds a handlers for the standard USB requests.

        This will handle all Standard-type requests; so any additional request handlers
        must not handle Standard requests.

        Parameters:

        """
        handler = StandardRequestHandler(descriptors)
        self._request_handlers.append(handler)


    def elaborate(self, platform):
        m = Module()

        # Shortcuts.
        interface      = self.interface
        handshakes_out = self.interface.handshakes_out
        handshakes_in  = self.interface.handshakes_in


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

        # Multiplex the output of each of our request handlers.
        m.submodules.request_mux = request_mux = SuperSpeedRequestHandlerMultiplexer()
        request_interface = request_mux.shared

        # Add each of our handlers to the endpoint; and add it to our mux.
        for handler in self._request_handlers:

            # Create a display name for the handler...
            name = handler.__class__.__name__
            if hasattr(m.submodules, name):
                name = f"{name}_{id(handler)}"

            # ... and add it.
            m.submodules[name] = handler
            request_mux.add_interface(handler.interface)


        # To simplify the request-handler interface, we'll only pass through our Rx stream
        # when the most recently header packet targets our endpoint number.
        with m.If(interface.rx_header.endpoint_number == self._endpoint_number):
            m.d.comb += [
                request_interface.rx           .tap(interface.rx),
                request_interface.rx_complete  .eq(interface.rx_complete),
                request_interface.rx_invalid   .eq(interface.rx_invalid),
            ]

        # The remainder of our signals are always hooked up.
        m.d.comb += [
            request_interface.rx_header    .eq(interface.rx_header),

            # Transmit. Note that our transmit direction is always set to OUT; even though we're
            # sending data to the host, per [USB3.2r1: 8.12.2].
            interface.tx                   .stream_eq(request_interface.tx),
            interface.tx_length            .eq(request_interface.tx_length),
            interface.tx_sequence_number   .eq(0),
            interface.tx_endpoint_number   .eq(self._endpoint_number),
            interface.tx_direction         .eq(USBDirection.OUT),

            # Status.
            interface.handshakes_in        .connect(request_interface.handshakes_in),
            interface.handshakes_out       .connect(request_interface.handshakes_out),

            # Address / config management.
            interface.address_changed      .eq(request_interface.address_changed),
            interface.new_address          .eq(request_interface.new_address),

            interface.config_changed       .eq(request_interface.config_changed),
            interface.new_config           .eq(request_interface.new_config),

        ]

        #
        # Data sequence handling.
        #

        #
        # SETUP stage handling.
        #

        # Our setup stage is easy: we just pass through our setup packet through to the request handlers...
        m.d.comb += request_interface.setup.eq(setup_decoder.packet)

        # ... and then ACK any SETUP packet that comes through, as we're required to [USB3.2r1: 8.12.2].
        # Note that our SETUP sequence number needs to be `1`.
        with m.If(setup_decoder.packet.received):
            m.d.comb += [
                handshakes_out.retry_required   .eq(0),
                handshakes_out.next_sequence    .eq(1),
                handshakes_out.send_ack         .eq(1),
            ]


        # Always set the endpoint number in our handshakes.
        m.d.comb += handshakes_out.endpoint_number  .eq(self._endpoint_number),

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
