#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Endpoint abstractions for USB3. """

import operator
import functools

from amaranth import *

from .transaction import HandshakeGeneratorInterface, HandshakeReceiverInterface

from ..link.data   import DataHeaderPacket
from ....utils.bus import OneHotMultiplexer
from ...stream     import SuperSpeedStreamInterface

class SuperSpeedEndpointInterface:
    """ Interface that connects a USB3 endpoint module to a USB device.

    Many non-control endpoints won't need to use the latter half of this structure;
    it will be automatically removed by the relevant synthesis tool.

    Attributes
    ----------
    rx: SuperSpeedStreamInterface(), input stream to endpoint
        Receive interface for this endpoint. This stream's ``ready`` signal is ignored.
    rx_header: DataHeaderPacket(), input to endpoint
        The header associated with the packet currently being received.
    rx_complete: Signal(), input to endpoint
        Strobe that indicates that the concluding rx-stream was valid (CRC check passed).
    rx_invalid: Signal(), input to endpoint
        Strobe that indicates that the concluding rx-stream was invalid (CRC check failed).
    rx_new_header: Signal(), input to endpoint
        Strobe; indicates that a new header is available on rx_header.

    tx: SuperSpeedStreamInterface(), output stream from endpoint
        Transmit interface for this endpoint. This stream's ``valid`` must remain high for
        an entire packet; and it must respect the transmitter's ``ready`` signal.
    tx_zlp: Signal(), output from endpoint
        Strobe; when pulsed, triggers sending of a zero-length packet.
    tx_length: Signal(range(1024 + 1)), output from endpoint
        The length of the packet to be transmitted; required for generating its header.
    tx_endpoint_number: Signal(4), output from endpoint
        The endpoint number associated with the active transmission.
    tx_sequence_number: Signal(4), output from endpoint
        The sequence number associated with the active transmission.
    tx_direction: Signal(), output from endpoint
        The direction associated with the active transmission; used for control endpoints.

    active_address: Signal(7), input to endpoint
        Contains the device's current address.
    address_changed: Signal(), output from endpoint.
        Strobe; pulses high when the device's address should be changed.
    new_address: Signal(7), output from endpoint
        When :attr:`address_changed` is high, this field contains the address that should be adopted.

    active_config: Signal(8), input to endpoint
        The configuration number of the active configuration.
    config_changed: Signal(), output from endpoint
        Strobe; pulses high when the device's configuration should be changed.
    new_config: Signal(8)
        When `config_changed` is high, this field contains the configuration that should be applied.
    """

    def __init__(self):

        # Data packet reception.
        self.rx                    = SuperSpeedStreamInterface()
        self.rx_header             = DataHeaderPacket()
        self.rx_complete           = Signal()
        self.rx_invalid            = Signal()

        # Data packet transmission.
        self.tx                    = SuperSpeedStreamInterface()
        self.tx_zlp                = Signal()
        self.tx_length             = Signal(range(1024 + 1))
        self.tx_endpoint_number    = Signal(4)
        self.tx_sequence_number    = Signal(5)
        self.tx_direction          = Signal(reset=1)

        # Handshaking / transaction packet exchange.
        self.handshakes_out        = HandshakeGeneratorInterface()
        self.handshakes_in         = HandshakeReceiverInterface()

        # Endpoint state.
        self.ep_reset              = Signal()

        # Typically only used for control endpoints.
        self.active_address        = Signal(7)
        self.address_changed       = Signal()
        self.new_address           = Signal(7)

        self.active_config         = Signal(8)
        self.config_changed        = Signal()
        self.new_config            = Signal(8)



class SuperSpeedEndpointMultiplexer(Elaboratable):
    """ Multiplexes access to the resources shared between multiple endpoint interfaces.

    Interfaces are added using :attr:`add_interface`.

    Attributes
    ----------

    shared: SuperSpeedEndpointInterface
        The post-multiplexer endpoint interface.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.shared = SuperSpeedEndpointInterface()

        #
        # Internals
        #
        self._interfaces = []


    def add_interface(self, interface: SuperSpeedEndpointInterface):
        """ Adds a EndpointInterface to the multiplexer.

        Arbitration is not performed; it's expected only one endpoint will be
        driving the transmit lines at a time.
        """
        self._interfaces.append(interface)


    def _multiplex_signals(self, m, *, when, multiplex):
        """ Helper that creates a simple priority-encoder multiplexer.

        Parmeters
        ---------
        when: str
            The name of the interface signal that indicates that the `multiplex` signals should be
            selected for output. If this signals should be multiplexed, it should be included in `multiplex`.
        multiplex: iterable(str)
            The names of the interface signals to be multiplexed.
        """

        # We're building an if-elif tree; so we should start with an If entry.
        conditional = m.If

        for interface in self._interfaces:
            condition = getattr(interface, when)

            with conditional(condition):

                # Connect up each of our signals.
                for signal_name in multiplex:

                    # Get the actual signals for our input and output...
                    driving_signal = getattr(interface,   signal_name)
                    target_signal  = getattr(self.shared, signal_name)

                    # ... and connect them.
                    m.d.comb += target_signal   .eq(driving_signal)

            # After the first element, all other entries should be created with Elif.
            conditional = m.Elif



    def elaborate(self, platform):
        m = Module()
        shared = self.shared

        #
        # Pass through signals being routed -to- our pre-mux interfaces.
        #
        for interface in self._interfaces:
            m.d.comb += [

                # Rx interface.
                interface.rx                     .tap(shared.rx),
                interface.rx_header              .eq(shared.rx_header),
                interface.rx_complete            .eq(shared.rx_complete),
                interface.rx_invalid             .eq(shared.rx_invalid),

                # Handshake exchange.
                shared.handshakes_in             .connect(interface.handshakes_in),

                # State signals.
                interface.ep_reset               .eq(shared.config_changed),
                interface.active_config          .eq(shared.active_config),
                interface.active_address         .eq(shared.active_address)
            ]

        #
        # Multiplex each of our transmit interfaces.
        #
        for interface in self._interfaces:

            # If the transmit interface is valid, connect it up to our endpoint.
            # The latest assignment will win; so we can treat these all as a parallel 'if's
            # and still get an appropriate priority encoder.
            with m.If(interface.tx.valid.any() | interface.tx_zlp):
                m.d.comb += [
                    shared.tx                  .stream_eq(interface.tx),
                    shared.tx_zlp              .eq(interface.tx_zlp),
                    shared.tx_direction        .eq(interface.tx_direction),
                    shared.tx_endpoint_number  .eq(interface.tx_endpoint_number),
                    shared.tx_sequence_number  .eq(interface.tx_sequence_number),
                    shared.tx_length           .eq(interface.tx_length)
                ]


        #
        # Multiplex each of our handshake-out interfaces.
        #
        for interface in self._interfaces:
            any_generate_signal_asserted = (
                interface.handshakes_out.send_ack   |
                interface.handshakes_out.send_stall
            )

            # If the given interface is trying to send an handshake, connect it up
            # to our shared interface.
            with m.If(any_generate_signal_asserted):
                m.d.comb += shared.handshakes_out.connect(interface.handshakes_out)


        #
        # Multiplex the signals being routed -from- our pre-mux interface.
        #
        self._multiplex_signals(m,
            when='address_changed',
            multiplex=['address_changed', 'new_address']
        )
        self._multiplex_signals(m,
            when='config_changed',
            multiplex=['config_changed', 'new_config']
        )


        return m
