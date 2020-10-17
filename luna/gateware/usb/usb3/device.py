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

from nmigen import *

from usb_protocol.emitters import DeviceDescriptorCollection

# USB3 Protocol Stack
from .physical             import USB3PhysicalLayer
from .link                 import USB3LinkLayer
from .protocol             import USB3ProtocolLayer
from .endpoints            import USB3ControlEndpoint

# Temporary
from ..stream              import USBRawSuperSpeedStream, SuperSpeedStreamInterface


class USBSuperSpeedDevice(Elaboratable):
    """ Core gateware common to all LUNA USB3 devices. """

    def __init__(self, *, phy, sync_frequency=None):
        self._phy = phy
        self._sync_frequency = sync_frequency


        # TODO: remove when complete
        logging.warning("USB3 device support is not at all complete!")
        logging.warning("Do not expect -anything- to work!")

        # TODO: replace this with a real endpoint collection
        self._control_endpoint = None

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

        # TODO: build a collection of endpoint interfaces, and arbitrate between them
        # FIXME: remove this scaffolding, and replace it with a real interface.
        self._control_endpoint = USB3ControlEndpoint(descriptors=descriptors)


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



        # TODO: build a collection of endpoint interfaces, and arbitrate between them
        # FIXME: remove this scaffolding, and replace it with a real interface.
        m.submodules.control_ep = control_ep = self._control_endpoint
        m.d.comb += [

            # Receive interface.
            control_ep.interface.rx                         .tap(protocol.endpoint_interface.rx),
            control_ep.interface.rx_header                  .eq(protocol.endpoint_interface.rx_header),
            control_ep.interface.rx_complete                .eq(protocol.endpoint_interface.rx_complete),
            control_ep.interface.rx_invalid                 .eq(protocol.endpoint_interface.rx_invalid),

            # Transmit interface.
            protocol.endpoint_interface.tx                  .stream_eq(control_ep.interface.tx),
            protocol.endpoint_interface.tx_length           .eq(control_ep.interface.tx_length),
            protocol.endpoint_interface.tx_endpoint_number  .eq(control_ep.interface.tx_endpoint_number),
            protocol.endpoint_interface.tx_sequence_number  .eq(control_ep.interface.tx_sequence_number),
            protocol.endpoint_interface.tx_direction        .eq(control_ep.interface.tx_direction),

            # Handshake interface.
            protocol.endpoint_interface.handshakes_out      .connect(control_ep.interface.handshakes_out),
            protocol.endpoint_interface.handshakes_in       .connect(control_ep.interface.handshakes_in)
        ]


        # If an endpoint wants to update our address or configuration, accept the update.
        with m.If(control_ep.interface.address_changed):
            m.d.ss += address.eq(control_ep.interface.new_address)
        with m.If(control_ep.interface.config_changed):
            m.d.ss += configuration.eq(control_ep.interface.new_config)



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
