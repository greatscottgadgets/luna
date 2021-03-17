#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD--3-Clause
""" Endpoint interfaces for isochronous endpoints.

These interfaces provide interfaces for connecting memories or memory-like
interfaces to hosts via isochronous pipes.
"""

from nmigen         import Elaboratable, Module, Signal

from ..endpoint     import EndpointInterface
from ...stream      import StreamInterface, USBOutStreamBoundaryDetector
from ....memory     import TransactionalizedFIFO

class USBIsochronousInEndpoint(Elaboratable):
    """ Isochronous endpoint that presents a memory-like interface.

    Used for repeatedly streaming data to a host from a memory or memory-like interface.
    Intended to be useful as a transport for e.g. video or audio data.

    Attributes
    ----------
    interface: EndpointInterface
        Communications link to our USB core.

    bytes_in_frame: Signal(range(0, 3073)), input
        Specifies how many bytes will be transferred during this frame. If this is 0,
        a single ZLP will be emitted; for any other value one, two, or three packets
        will be generated, depending on the packet size. Latched in at the start of
        each frame.

        The maximum allowed value for this signal depends on the number of transfers
        per (micro)frame:
        - If this is a high-speed, high-throughput endpoint (descriptor indicates
          maxPacketSize > 512 and multiple transfers per microframe), then this value
          maxes out at (N * maxPacketSize), where N is the number of transfers per microframe.
        - For all other configurations, this must be <= the maximum packet size.

    address: Signal(range(0,3072)), output
        Indicates the address / offset of the byte currently being transmitted.
        Can be used to drive the ``address` lines of an asynchronous memory
    next_address: Signal(range(0,3072)), output
        Indicates the "address" / offset of the byte that should be presented
        on :attr:``value`` at the next ``usb``-clock cycle. Can be used to drive
        the ``address`` lines of a synchronous memory.
    value: Signal(8), input
        The value to be transmitted, this cycle. Can be directly tied to the read
        port of a memory.

    Parameters
    ----------
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    max_packet_size: int
        The maximum packet size for this endpoint. Should match the wMaxPacketSize provided in the
        USB endpoint descriptor.
    """

    _MAX_FRAME_DATA = 1024 * 3

    def __init__(self, *, endpoint_number, max_packet_size):
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size

        #
        # I/O Port
        #
        self.interface      = EndpointInterface()

        self.bytes_in_frame = Signal(range(0, self._MAX_FRAME_DATA + 1))

        self.address        = Signal(range(0, self._MAX_FRAME_DATA))
        self.next_address   = Signal.like(self.address)
        self.value          = Signal(8)


    def elaborate(self, platform):
        m = Module()

        # Shortcuts.
        interface        = self.interface
        out_stream       = interface.tx
        new_frame        = interface.tokenizer.new_frame

        targeting_ep_num = (interface.tokenizer.endpoint == self._endpoint_number)
        targeting_us     = targeting_ep_num & interface.tokenizer.is_in
        data_requested   = targeting_us & interface.tokenizer.ready_for_response

        # Track our state in our transmission.
        bytes_left_in_frame  = Signal.like(self.bytes_in_frame)
        bytes_left_in_packet = Signal(range(0, self._max_packet_size + 1), reset=self._max_packet_size - 1)
        next_data_pid        = Signal(2)

        # Reset our state at the start of each frame.
        with m.If(new_frame):

            m.d.usb += [
                # Latch in how many bytes we'll be transmitting this frame.
                bytes_left_in_frame.eq(self.bytes_in_frame),

                # And start with a full packet to transmit.
                bytes_left_in_packet.eq(self._max_packet_size)
            ]

            # If it'll take more than two packets to send our data, start off with DATA2.
            # We'll follow with DATA1 and DATA0.
            with m.If(self.bytes_in_frame > (2 * self._max_packet_size)):
                m.d.usb += next_data_pid.eq(2)

            # Otherwise, if we need two, start with DATA1.
            with m.Elif(self.bytes_in_frame > self._max_packet_size):
                m.d.usb += next_data_pid.eq(1)

            # Otherwise, we'll start (and end) with DATA0.
            with m.Else():
                m.d.usb += next_data_pid.eq(0)


        m.d.comb += [
            # Always pass our ``value`` directly through to our transmitter.
            # We'll provide ``address``/``next_address`` to our user code to help
            # orchestrate this timing.
            out_stream.payload       .eq(self.value),

            # Provide our data pid through to to the transmitter.
            interface.tx_pid_toggle  .eq(next_data_pid)
        ]

        #
        # Core sequencing FSM.
        #
        with m.FSM(domain="usb"):

            # IDLE -- the host hasn't yet requested data from our endpoint.
            with m.State("IDLE"):
                m.d.usb  += [
                    # Remain targeting the first byte in our frame.
                    self.address      .eq(0),
                    out_stream.first  .eq(0)
                ]

                m.d.comb += self.next_address.eq(0)

                # Once the host requests a packet from us...
                with m.If(data_requested):

                    # If we have data to send, send it.
                    with m.If(bytes_left_in_frame):
                        m.d.usb += out_stream.first.eq(1)
                        m.next = "SEND_DATA"

                    # Otherwise, we'll send a ZLP.
                    with m.Else():
                        m.next = "SEND_ZLP"


            # SEND_DATA -- our primary data-transmission state; handles packet transmission
            with m.State("SEND_DATA"):
                last_byte_in_packet    = (bytes_left_in_packet <= 1)
                last_byte_in_frame     = (bytes_left_in_frame  <= 1)
                byte_terminates_send   = last_byte_in_packet | last_byte_in_frame

                m.d.comb += [
                    # Our data is always valid in this state...
                    out_stream.valid .eq(1),

                    # ... and we're terminating our packet if we're on the last byte of it.
                    out_stream.last  .eq(byte_terminates_send),
                ]

                # ``address`` should always move to the value presented in
                # ``next_address`` on each clock edge.
                m.d.usb += self.address.eq(self.next_address)

                # By default, don't advance.
                m.d.comb += self.next_address.eq(self.address)

                # We'll advance each time our data is accepted.
                with m.If(out_stream.ready):
                    m.d.usb += out_stream.first.eq(0)

                    # Mark the relevant byte as sent...
                    m.d.usb += [
                        bytes_left_in_frame   .eq(bytes_left_in_frame  - 1),
                        bytes_left_in_packet  .eq(bytes_left_in_packet - 1),
                    ]

                    # ... and advance to the next address.
                    m.d.comb += self.next_address.eq(self.address + 1)

                    # If we've just completed transmitting a packet, or we've
                    # just transmitted a full frame, end our transmission.
                    with m.If(byte_terminates_send):
                        m.d.usb += [
                            # Move to the next DATA pid, which is always one DATA PID less.
                            # [USB2.0: 5.9.2]. We'll reset this back to its maximum value when
                            # the next frame starts.
                            next_data_pid        .eq(next_data_pid - 1),

                            # Mark our next packet as being a full one.
                            bytes_left_in_packet .eq(self._max_packet_size)
                        ]
                        m.next = "IDLE"


            # SEND_ZLP -- sends a zero-length packet, and then return to idle.
            with m.State("SEND_ZLP"):
                # We'll request a ZLP by strobing LAST and VALID without strobing FIRST.
                m.d.comb += [
                    out_stream.valid  .eq(1),
                    out_stream.last   .eq(1),
                ]
                m.next = "IDLE"

        return m


class USBIsochronousOutEndpoint(Elaboratable):
    """ Endpoint interface that receives isochronous data from the host, and produces a simple data stream.

    Used for repeatedly streaming data from a host.
    Intended to be useful as a transport for e.g. video or audio data.


    Attributes
    ----------
    stream: StreamInterface, output stream
        Full-featured stream interface that carries the data we've received from the host.
        Note that this stream is *transaction* oriented; which means that First and Last indicate
        the start and end of an individual data packet. This means that short packet detection is
        the responsibility of the stream's consumer.
    interface: EndpointInterface
        Communications link to our USB device.

    Parameters
    ----------
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    max_packet_size: int
        The maximum packet size for this endpoint. If this there isn't either
        `buffer_size` of, if not given, `max_packet_size * 2` space in
        the endpoint buffer, this endpoint will silently discard the extraneous data
    buffer_size: int, optional
        The total amount of data we'll keep in the buffer; typically three max-packet-sizes or more.
        Defaults to twice the maximum packet size.
    """


    def __init__(self, *, endpoint_number, max_packet_size, buffer_size=None):
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size
        self._buffer_size = buffer_size if (buffer_size is not None) else (self._max_packet_size * 2)

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

        # Stores whether this is the first byte of a transfer. True if the previous byte had its `last` bit set.
        is_first_byte = Signal(reset=1)

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

        # Generate our `first` bit from the most recently transmitted bit.
        # Essentially, if the most recently valid byte was accompanied by an asserted `last`, the next byte
        # should have `first` asserted.
        with m.If(stream.valid & stream.ready):
            m.d.usb += is_first_byte.eq(stream.last)

        #
        # Create some basic conditionals that will help us make decisions.
        #

        endpoint_number_matches  = (tokenizer.endpoint == self._endpoint_number)
        targeting_endpoint       = endpoint_number_matches & tokenizer.is_out
        sufficient_space         = (fifo.space_available >= self._max_packet_size)
        okay_to_receive          = targeting_endpoint & sufficient_space

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

        return m
