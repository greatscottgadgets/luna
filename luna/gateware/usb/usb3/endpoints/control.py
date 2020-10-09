#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Low-level USB3 transciever gateware -- control transfer components. """

from nmigen import *

from ..protocol.endpoint   import SuperSpeedEndpointInterface
from usb_protocol.emitters import DeviceDescriptorCollection
from usb_protocol.types    import USBRequestType

from ..protocol.data       import SuperSpeedSetupDecoder


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



    def elaborate(self, platform):
        m = Module()
        interface = self.interface

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
        # Transaction packet interface.
        #

        # FIXME: replace this scaffolding
        handshakes_out = interface.handshakes_out
        m.d.comb += [
            handshakes_out.endpoint_number  .eq(self._endpoint_number),
            handshakes_out.next_sequence    .eq(0),
            handshakes_out.retry_required   .eq(0)
        ]


        with m.If(setup_decoder.packet.received):
            m.d.comb += handshakes_out.send_ack.eq(1)

        with m.If(interface.handshakes_in.status_received):
            m.d.comb += handshakes_out.send_ack.eq(1)


        # FIXME: implement our control endpoint!

        return m
