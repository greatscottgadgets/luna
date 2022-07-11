#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Endpoint interfaces for working with streams.

The endpoint interfaces in this module provide endpoint interfaces suitable for
connecting streams to USB endpoints.
"""

from amaranth       import Elaboratable, Module, Signal

from ..endpoint     import EndpointInterface
from ...stream      import StreamInterface, USBOutStreamBoundaryDetector
from ..transfer     import USBInTransferManager
from ....memory     import TransactionalizedFIFO


class USBStreamInEndpoint(Elaboratable):
    """ Endpoint interface that transmits a simple data stream to a host.

    This interface is suitable for a single bulk or interrupt endpoint.

    This endpoint interface will automatically generate ZLPs when a stream packet would end without
    a short data packet. If the stream's ``last`` signal is tied to zero, then a continuous stream of
    maximum-length-packets will be sent with no inserted ZLPs.

    This implementation is double buffered; and can store a single packets worth of data while transmitting
    a second packet.


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
            tx_manager.transfer_stream  .stream_eq(self.stream),

            # ... and our output stream...
            interface.tx                .stream_eq(tx_manager.packet_stream),
            interface.tx_pid_toggle     .eq(tx_manager.data_pid),

            # ... and connect through our token/handshake signals.
            interface.tokenizer         .connect(tx_manager.tokenizer),
            tx_manager.handshakes_out   .connect(interface.handshakes_out),
            interface.handshakes_in     .connect(tx_manager.handshakes_in)
        ]

        return m



class USBMultibyteStreamInEndpoint(Elaboratable):
    """ Endpoint interface that transmits a simple data stream to a host.

    This interface is suitable for a single bulk or interrupt endpoint.

    This variant accepts streams with payload sizes that are a multiple of one byte; data is always
    transmitted to the host in little-endian byte order.

    This endpoint interface will automatically generate ZLPs when a stream packet would end without
    a short data packet. If the stream's ``last`` signal is tied to zero, then a continuous stream of
    maximum-length-packets will be sent with no inserted ZLPs.

    This implementation is double buffered; and can store a single packets worth of data while transmitting
    a second packet.


    Attributes
    ----------
    stream: StreamInterface, input stream
        Full-featured stream interface that carries the data we'll transmit to the host.
    interface: EndpointInterface
        Communications link to our USB device.


    Parameters
    ----------
    byte_width: int
        The number of bytes to be accepted at once.
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    max_packet_size: int
        The maximum packet size for this endpoint. Should match the wMaxPacketSize provided in the
        USB endpoint descriptor.
    """
    def __init__(self, *, byte_width, endpoint_number, max_packet_size):
        self._byte_width      = byte_width
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size

        #
        # I/O port
        #
        self.stream          = StreamInterface(payload_width=byte_width * 8)
        self.interface       = EndpointInterface()


    def elaborate(self, platform):
        m = Module()

        # Create our core, single-byte-wide endpoint, and attach it directly to our interface.
        m.submodules.stream_ep = stream_ep = USBStreamInEndpoint(
            endpoint_number=self._endpoint_number,
            max_packet_size=self._max_packet_size
        )
        stream_ep.interface = self.interface

        # Create semantic aliases for byte-wise and word-wise streams;
        # so the code below reads more clearly.
        byte_stream = stream_ep.stream
        word_stream = self.stream

        # We'll put each word to be sent through an shift register
        # that shifts out words a byte at a time.
        data_shift = Signal.like(word_stream.payload)

        # Latched versions of our first and last signals.
        first_latched = Signal()
        last_latched  = Signal()

        # Count how many bytes we have left to send.
        bytes_to_send = Signal(range(0, self._byte_width + 1))

        # Always provide our inner transmitter with the least byte of our shift register.
        m.d.comb += byte_stream.payload.eq(data_shift[0:8])


        with m.FSM(domain="usb"):

            # IDLE: transmitter is waiting for input
            with m.State("IDLE"):
                m.d.comb += word_stream.ready.eq(1)

                # Once we get a send request, fill in our shift register, and start shifting.
                with m.If(word_stream.valid):
                    m.d.usb += [
                        data_shift         .eq(word_stream.payload),
                        first_latched      .eq(word_stream.first),
                        last_latched       .eq(word_stream.last),

                        bytes_to_send      .eq(self._byte_width - 1),
                    ]
                    m.next = "TRANSMIT"


            # TRANSMIT: actively send each of the bytes of our word
            with m.State("TRANSMIT"):
                m.d.comb += byte_stream.valid.eq(1)

                # Once the byte-stream is accepting our input...
                with m.If(byte_stream.ready):
                    is_first_byte = (bytes_to_send == self._byte_width - 1)
                    is_last_byte  = (bytes_to_send == 0)

                    # Pass through our First and Last signals, but only on the first and
                    # last bytes of our word, respectively.
                    m.d.comb += [
                        byte_stream.first  .eq(first_latched & is_first_byte),
                        byte_stream.last   .eq(last_latched  & is_last_byte)
                    ]

                    # ... if we have bytes left to send, move to the next one.
                    with m.If(bytes_to_send > 0):
                        m.d.usb += [
                            bytes_to_send .eq(bytes_to_send - 1),
                            data_shift    .eq(data_shift[8:]),
                        ]

                    # Otherwise, complete the frame.
                    with m.Else():
                        m.d.comb += word_stream.ready.eq(1)

                        # If we still have data to send, move to the next byte...
                        with m.If(self.stream.valid):
                            m.d.usb += [
                                data_shift     .eq(word_stream.payload),
                                first_latched  .eq(word_stream.first),
                                last_latched   .eq(word_stream.last),

                                bytes_to_send  .eq(self._byte_width - 1),
                            ]

                        # ... otherwise, move to our idle state.
                        with m.Else():
                            m.next = "IDLE"


        return m



class USBStreamOutEndpoint(Elaboratable):
    """ Endpoint interface that receives data from the host, and produces a simple data stream.

    This interface is suitable for a single bulk or interrupt endpoint.


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
    max_packet_size: int
        The maximum packet size for this endpoint. If this there isn't `max_packet_size` space in
        the endpoint buffer, this endpoint will NAK (or participate in the PING protocol.)
    buffer_size: int, optional
        The total amount of data we'll keep in the buffer; typically two max-packet-sizes or more.
        Defaults to twice the maximum packet size.
    """


    def __init__(self, *, endpoint_number, max_packet_size, buffer_size=None):
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size
        self._buffer_size = buffer_size if (buffer_size is not None) else (self._max_packet_size * 2 - 1)

        #
        # I/O port
        #
        self.stream    = StreamInterface()
        self.interface = EndpointInterface()


    def elaborate(self, platform):
        m = Module()

        stream    = self.stream
        interface = self.interface
        tokenizer = interface.tokenizer

        #
        # Internal state.
        #

        # Stores the data toggle value we expect.
        expected_data_toggle = Signal()

        # Stores whether we've had a receive overflow.
        overflow = Signal()

        # Stores a count of received bytes in the current packet.
        rx_cnt = Signal(range(self._max_packet_size))

        # Stores whether we're in the middle of a transfer.
        transfer_active = Signal()

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

        expected_pid_match       = (interface.rx_pid_toggle == expected_data_toggle)
        sufficient_space         = (fifo.space_available >= self._max_packet_size)

        ping_response_requested  = endpoint_number_matches & tokenizer.is_ping & tokenizer.ready_for_response
        data_response_requested  = targeting_endpoint & tokenizer.is_out & interface.rx_ready_for_response

        okay_to_receive          = targeting_endpoint & expected_pid_match
        data_is_lost             = okay_to_receive & rx.next & rx.valid & fifo.full
        data_accepted            = okay_to_receive & ~data_is_lost & ~overflow
        should_skip              = targeting_endpoint & ~expected_pid_match

        full_packet              = rx_cnt == self._max_packet_size - 1

        m.d.comb += [

            # We'll always populate our FIFO directly from the receive stream; but we'll also include our
            # "short packet detected" signal, as this indicates that we're detecting the last byte of a transfer.
            fifo.write_data[0:8] .eq(rx.payload),
            fifo.write_data[8]   .eq(rx_last & ~full_packet),
            fifo.write_data[9]   .eq(rx_first & ~transfer_active),
            fifo.write_en        .eq(okay_to_receive & rx.next & rx.valid & ~fifo.full),

            # We'll keep data if our packet finishes with a valid CRC and no overflow; and discard it otherwise.
            fifo.write_commit    .eq(targeting_endpoint & boundary_detector.complete_out & ~overflow),
            fifo.write_discard   .eq(targeting_endpoint & (boundary_detector.invalid_out | (boundary_detector.complete_out & overflow))),

            # We'll ACK each packet if it's received correctly; _or_ if we skipped the packet
            # due to a PID sequence mismatch. If we get a PID sequence mismatch, we assume that
            # we missed a previous ACK from the host; and ACK without accepting data [USB 2.0: 8.6.3].
            interface.handshakes_out.ack  .eq(
                (data_response_requested & data_accepted) |
                (ping_response_requested & sufficient_space) |
                (data_response_requested & should_skip)
            ),

            # We'll NAK any time we want to accept a packet, but we don't have enough room.
            interface.handshakes_out.nak  .eq(
                (data_response_requested & ~data_accepted & ~should_skip) |
                (ping_response_requested & ~sufficient_space)
            ),

            # Our stream data always comes directly out of the FIFO; and is valid
            # henever our FIFO actually has data for us to read.
            stream.valid      .eq(~fifo.empty),
            stream.payload    .eq(fifo.read_data[0:8]),

            # Our `last` bit comes directly from the FIFO; and we know a `first` bit immediately
            # follows a `last` one.
            stream.last       .eq(fifo.read_data[8]),
            stream.first      .eq(fifo.read_data[9]),

            # Move to the next byte in the FIFO whenever our stream is advaced.
            fifo.read_en      .eq(stream.ready),
            fifo.read_commit  .eq(1)
        ]

        # Count bytes in packet.
        with m.If(fifo.write_en):
            m.d.usb += rx_cnt.eq(rx_cnt + 1)

            # Set the transfer active flag depending on whether this is a full packet.
            with m.If(rx_last):
                m.d.usb += transfer_active.eq(full_packet)

        # We'll set the overflow flag if we're receiving data we don't have room for.
        with m.If(data_is_lost):
            m.d.usb += overflow.eq(1)

        # We'll clear the overflow flag and byte counter when the packet is done.
        with m.Elif(fifo.write_commit | fifo.write_discard):
            m.d.usb += overflow.eq(0)
            m.d.usb += rx_cnt.eq(0)

        # We'll toggle our DATA PID each time we issue an ACK to the host [USB 2.0: 8.6.2].
        with m.If(data_response_requested & data_accepted):
            m.d.usb += expected_data_toggle.eq(~expected_data_toggle)


        return m

