#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
"""
Contains the organizing hardware used to add USB3 Device functionality
to your own designs; including the core :class:`USBSuperSpeedDevice` class.
"""

import logging

from amaranth import *

from usb_protocol.emitters import DeviceDescriptorCollection

# USB3 Protocol Stack
from .physical             import USB3PhysicalLayer
from .link                 import USB3LinkLayer
from .protocol             import USB3ProtocolLayer
from .endpoints            import USB3ControlEndpoint
from .protocol.endpoint    import SuperSpeedEndpointMultiplexer

# Temporary
from ..stream              import USBRawSuperSpeedStream, SuperSpeedStreamInterface


class USBSuperSpeedDevice(Elaboratable):
    """ Core gateware common to all LUNA USB3 devices. """

    def __init__(self, *, phy, sync_frequency=None):
        self._phy = phy
        self._sync_frequency = sync_frequency

        # Create a collection of endpoints for this device.
        self._endpoints = []

        #
        # I/O port
        #

        # General status signals.
        self.link_trained   = Signal()
        self.link_in_reset  = Signal()

        # Temporary, debug signals.
        self.rx_data_tap         = USBRawSuperSpeedStream()
        self.tx_data_tap         = USBRawSuperSpeedStream()

        self.ep_tx_stream        = SuperSpeedStreamInterface()
        self.ep_tx_length        = Signal(range(1024 + 1))


    def add_endpoint(self, endpoint):
        """ Adds an endpoint interface to the device.

        Parameters
        ----------
        endpoint: Elaborateable
            The endpoint interface to be added. Can be any piece of gateware with a
            :class:`EndpointInterface` attribute called ``interface``.
        """
        self._endpoints.append(endpoint)


    def add_standard_control_endpoint(self, descriptors: DeviceDescriptorCollection):
        """ Adds a control endpoint with standard request handlers to the device.

        Parameters
        ----------
        descriptors: DeviceDescriptorCollection
            The descriptors to use for this device.

        Return value
        ------------
        The endpoint object created.
        """

        # TODO: split out our standard request handlers

        control_endpoint = USB3ControlEndpoint()
        control_endpoint.add_standard_request_handlers(descriptors)
        self.add_endpoint(control_endpoint)

        return control_endpoint



    def elaborate(self, platform):
        m = Module()

        # Figure out the frequency of our ``sync`` domain, for e.g. PHY bringup timing.
        # We'll default to the platform's default frequency if none was provided.
        sync_frequency = self._sync_frequency
        if sync_frequency is None:
            sync_frequency = platform.default_clk_frequency

        #
        # Global device state.
        #

        # Stores the device's current address. Used to identify which packets are for us.
        address       = Signal(7, reset=0)

        # Stores the device's current configuration. Defaults to unconfigured.
        configuration = Signal(8, reset=0)


        #
        # Physical layer.
        #
        m.submodules.physical = physical = USB3PhysicalLayer(
            phy            = self._phy,
            sync_frequency = sync_frequency
        )

        #
        # Link layer.
        #
        m.submodules.link = link = USB3LinkLayer(physical_layer=physical)
        m.d.comb += [
            self.link_trained     .eq(link.trained),
            self.link_in_reset    .eq(link.in_reset),

            link.current_address  .eq(address)
        ]

        #
        # Protocol layer.
        #
        m.submodules.protocol = protocol = USB3ProtocolLayer(link_layer=link)
        m.d.comb += [
            protocol.current_address        .eq(address),
            protocol.current_configuration  .eq(configuration)
        ]


        #
        # Application layer.
        #

        # Create our endpoint multiplexer...
        m.submodules.endpoint_mux = endpoint_mux = SuperSpeedEndpointMultiplexer()
        endpoint_collection = endpoint_mux.shared

        m.d.comb += [
            # Receive interface.
            endpoint_collection.rx                          .tap(protocol.endpoint_interface.rx),
            endpoint_collection.rx_header                   .eq(protocol.endpoint_interface.rx_header),
            endpoint_collection.rx_complete                 .eq(protocol.endpoint_interface.rx_complete),
            endpoint_collection.rx_invalid                  .eq(protocol.endpoint_interface.rx_invalid),

            # Transmit interface.
            protocol.endpoint_interface.tx                  .stream_eq(endpoint_collection.tx),
            protocol.endpoint_interface.tx_zlp              .eq(endpoint_collection.tx_zlp),
            protocol.endpoint_interface.tx_length           .eq(endpoint_collection.tx_length),
            protocol.endpoint_interface.tx_endpoint_number  .eq(endpoint_collection.tx_endpoint_number),
            protocol.endpoint_interface.tx_sequence_number  .eq(endpoint_collection.tx_sequence_number),
            protocol.endpoint_interface.tx_direction        .eq(endpoint_collection.tx_direction),

            # Handshake interface.
            protocol.endpoint_interface.handshakes_out      .connect(endpoint_collection.handshakes_out),
            protocol.endpoint_interface.handshakes_in       .connect(endpoint_collection.handshakes_in)
        ]


        # If an endpoint wants to update our address or configuration, accept the update.
        with m.If(endpoint_collection.address_changed):
            m.d.ss += address.eq(endpoint_collection.new_address)
        with m.If(endpoint_collection.config_changed):
            m.d.ss += configuration.eq(endpoint_collection.new_config)


        # Finally, add each of our endpoints to this module and our multiplexer.
        for endpoint in self._endpoints:

            # Create a display name for the endpoint...
            name = endpoint.__class__.__name__
            if hasattr(m.submodules, name):
                name = f"{name}_{id(endpoint)}"

            # ... and add it, both as a submodule and to our multiplexer.
            endpoint_mux.add_interface(endpoint.interface)
            m.submodules[name] = endpoint


        #
        # Reset handling.
        #

        # Restore ourselves to our unconfigured state when a reset occurs.
        with m.If(link.in_reset):
            m.d.ss += [
                address        .eq(0),
                configuration  .eq(0)
            ]


        #
        # Debug helpers.
        #

        # Tap our transmit and receive lines, so they can be externally analyzed.
        m.d.comb += [
            self.rx_data_tap   .tap(physical.source),
            self.tx_data_tap   .tap(physical.sink),

            self.ep_tx_stream  .tap(protocol.endpoint_interface.tx, tap_ready=True),
            self.ep_tx_length  .eq(protocol.endpoint_interface.tx_length)
        ]


        return m
