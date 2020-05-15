#
# This file is part of LUNA.
#
""" Endpoint interfaces for working with streams.

The endpoint interfaces in this module provide endpoint interfaces suitable for
connecting streams to USB endpoints.
"""

from nmigen         import Elaboratable, Module
from ..endpoint     import EndpointInterface
from ...stream      import StreamInterface
from ..transfer     import USBInTransferManager


class USBStreamInEndpoint(Elaboratable):
    """ Endpoint interface that transmits a simple data stream to a host.

    This interface is suitable for a single bulk or interrupt endpoint.

    This endpoint interface will automatically generate ZLPs when a stream packet would end without
    a short data packet. If the stream's ``last`` signal is tied to zero, then a continuous stream of
    maximum-length-packets will be sent with no inserted ZLPs.


    Attributes
    ----------
    stream: StreamInterface, input stream
        Full-featured stream interface that carries the data we'll transmit to the host.

    interface: EndpointInterface
        Communications link to our USB device.


    Parameters
    ----------
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    max_packet_size: int
        The maximum packet size for this endpoint. Should match the wMaxPacketSize provided in the
        USB endpoint descriptor.
    """


    def __init__(self, *, endpoint_number, max_packet_size):

        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size

        #
        # I/O port
        #
        self.stream    = StreamInterface()
        self.interface = EndpointInterface()


    def elaborate(self, platform):
        m = Module()
        interface = self.interface

        # Create our transfer manager, which will be used to sequence packet transfers for our stream.
        m.submodules.tx_manager = tx_manager = USBInTransferManager(self._max_packet_size)

        m.d.comb += [

            # Always generate ZLPs; in order to pass along when stream packets terminate.
            tx_manager.generate_zlps    .eq(1),

            # We want to handle packets only that target our endpoint number.
            tx_manager.active           .eq(interface.tokenizer.endpoint == self._endpoint_number),

            # Connect up our transfer manager to our input stream...
            tx_manager.transfer_stream  .connect(self.stream),

            # ... and our output stream...
            interface.tx                .connect(tx_manager.packet_stream),
            interface.tx_pid_toggle     .eq(tx_manager.data_pid),

            # ... and connect through our token/handshake signals.
            interface.tokenizer         .connect(tx_manager.tokenizer),
            tx_manager.handshakes_out   .connect(interface.handshakes_out),
            interface.handshakes_in     .connect(tx_manager.handshakes_in)
        ]

        return m
