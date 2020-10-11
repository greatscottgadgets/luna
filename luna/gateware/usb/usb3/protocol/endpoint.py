#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Endpoint abstractions for USB3. """

from nmigen import *

from .transaction import HandshakeGeneratorInterface, HandshakeReceiverInterface

from ..link.data  import DataHeaderPacket
from ...stream    import SuperSpeedStreamInterface


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
    tx_length: Signal(range(1024 + 1))
        The length of the packet to be transmitted; required for generating its header.

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
        self.tx_length             = Signal(range(1024 + 1))
        self.tx_endpoint_number    = Signal(4)
        self.tx_sequence_number    = Signal(5)

        # Handshaking / transcation packet exchange.
        self.handshakes_out        = HandshakeGeneratorInterface()
        self.handshakes_in         = HandshakeReceiverInterface()


        # Typically only used for control endpoints.
        self.active_address        = Signal(7)
        self.address_changed       = Signal()
        self.new_address           = Signal(7)

        self.active_config         = Signal(8)
        self.config_changed        = Signal()
        self.new_config            = Signal(8)
