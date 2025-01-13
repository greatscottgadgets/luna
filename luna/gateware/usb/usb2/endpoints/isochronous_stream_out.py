#
# This file is part of LUNA.
#
# Copyright (c) 2020-2025 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Endpoint interfaces for isochronous endpoints.

These interfaces provide interfaces for connecting streams or stream-like
interfaces to hosts via isochronous pipes.
"""

from amaranth              import *
from amaranth.lib          import stream, wiring
from amaranth.lib .wiring  import In, Out

from ..endpoint            import EndpointInterface
from ...stream             import USBOutStreamBoundaryDetector
from ....stream.future     import Packet
from ....memory            import TransactionalizedFIFO


class USBIsochronousStreamOutEndpoint(Elaboratable):
    """ Endpoint interface that receives isochronous data from the host, and produces a simple data stream.

    Used for repeatedly streaming data from a host to a stream or stream-like interface.
    Intended to be useful as a transport for e.g. video or audio data.


    Attributes
    ----------
    stream: StreamInterface, output stream
        Full-featured stream interface that carries the data we've received from the host.
    interface: EndpointInterface
        Communications link to our USB device.

    Parameters
    ----------
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    max_packet_size: int, optional
        The maximum packet size for this endpoint. If there isn't `max_packet_size` space in
        the endpoint buffer, additional data will be silently dropped.
    buffer_size: int, optional
        The total amount of data we'll keep in the buffer; typically two (TODO three?) max-packet-sizes or more.
        Defaults to twice (TODO three?) times the maximum packet size.
    """

    def __init__(self, *, endpoint_number, max_packet_size, buffer_size=None):
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size
        # TODO self._buffer_size = buffer_size if (buffer_size is not None) else (self._max_packet_size * 3)
        self._buffer_size = buffer_size if (buffer_size is not None) else (self._max_packet_size * 2)

        #
        # I/O port
        #
        self.stream = stream.Interface(
            stream.Signature(
                Packet(unsigned(8))
            )
        )
        self.interface = EndpointInterface()

    def elaborate(self, platform):
        m = Module()

        stream    = self.stream
        interface = self.interface
        tokenizer = interface.tokenizer

        #
        # Internal state.
        #

        # Stores whether we've had a receive overflow.
        overflow = Signal()

        # Stores a count of received bytes in the current packet.
        rx_cnt = Signal(range(self._max_packet_size))

        #
        # Receiver logic.
        #

        # Create a version of our receive stream that has added `first` and `last` signals, which we'll use
        # internally as our main stream.
        m.submodules.boundary_detector = boundary_detector = USBOutStreamBoundaryDetector()
        m.d.comb += [
            interface.rx                   .stream_eq(boundary_detector.unprocessed_stream),
            boundary_detector.complete_in  .eq(interface.rx_complete),
            boundary_detector.invalid_in   .eq(interface.rx_invalid),
        ]

        rx       = boundary_detector.processed_stream
        rx_first = boundary_detector.first
        rx_last  = boundary_detector.last

        # Create a Rx FIFO.
        m.submodules.fifo = fifo = TransactionalizedFIFO(width=10, depth=self._buffer_size, name="rx_fifo", domain="usb")

        #
        # Create some basic conditionals that will help us make decisions.
        #

        endpoint_number_matches  = (tokenizer.endpoint == self._endpoint_number)
        targeting_endpoint       = endpoint_number_matches & tokenizer.is_out

        sufficient_space         = (fifo.space_available >= self._max_packet_size)

        okay_to_receive          = targeting_endpoint & sufficient_space
        data_is_lost             = okay_to_receive & rx.next & rx.valid & fifo.full

        full_packet              = rx_cnt == self._max_packet_size - 1

        m.d.comb += [

            # We'll always populate our FIFO directly from the receive stream; but we'll also include our
            # "short packet detected" signal, as this indicates that we're detecting the last byte of a transfer.
            fifo.write_data[0:8] .eq(rx.payload),
            fifo.write_data[8]   .eq(rx_last),
            fifo.write_data[9]   .eq(rx_first),
            fifo.write_en        .eq(okay_to_receive & rx.next & rx.valid),

            # We'll keep data if our packet finishes with a valid CRC; and discard it otherwise.
            fifo.write_commit    .eq(targeting_endpoint & boundary_detector.complete_out),
            fifo.write_discard   .eq(targeting_endpoint & boundary_detector.invalid_out),

            # Our stream data always comes directly out of the FIFO; and is valid
            # whenever our FIFO actually has data for us to read.
            stream.valid        .eq(~fifo.empty),
            stream.p.data       .eq(fifo.read_data[0:8]),

            # Our `last` bit comes directly from the FIFO; and we know a `first` bit immediately
            # follows a `last` one.
            stream.p.last        .eq(fifo.read_data[8]),
            stream.p.first       .eq(fifo.read_data[9]),

            # Move to the next byte in the FIFO whenever our stream is advanced.
            fifo.read_en         .eq(stream.ready),
            fifo.read_commit     .eq(1)
        ]

        # Count bytes in packet.
        with m.If(fifo.write_en):
            m.d.usb += rx_cnt.eq(rx_cnt + 1)

        # We'll set the overflow flag if we're receiving data we don't have room for.
        with m.If(data_is_lost):
            m.d.usb += overflow.eq(1)

        # We'll clear the overflow flag and byte counter when the packet is done.
        with m.Elif(fifo.write_commit | fifo.write_discard):
            m.d.usb += overflow.eq(0)
            m.d.usb += rx_cnt.eq(0)

        return m
