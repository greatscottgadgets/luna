#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD--3-Clause
""" Endpoint interfaces for isochronous endpoints.

These interfaces provide interfaces for connecting streams or stream-like
interfaces to hosts via isochronous pipes.
"""

from amaranth             import Elaboratable, Module, Signal, unsigned
# TODO from amaranth.lib         import stream

from ..endpoint           import EndpointInterface
from ...stream            import StreamInterface # TODO


class USBIsochronousStreamInEndpoint(Elaboratable):
    """ Isochronous endpoint that presents a stream-like interface.

    Used for repeatedly streaming data to a host from a stream-like interface.
    Intended to be useful as a transport for e.g. video or audio data.

    Attributes
    ----------
    stream: amaranth.lib.stream.Interface, input stream
        Full-featured stream interface that carries the data we'll transmit to the host.

    interface: EndpointInterface
        Communications link to our USB core.

    data_requested: Signal(), output
        Strobes, when a new packet starts

    frame_finished: Signal(), output
        Strobes immediately after the last byte in a frame has been transmitted

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
        # TODO self.stream         = stream.Interface(
        #     stream.Signature(unsigned(8))
        # )
        self.stream    = StreamInterface()
        self.data_requested = Signal()
        self.frame_finished = Signal()

        self.bytes_in_frame = Signal(range(0, self._MAX_FRAME_DATA + 1))

    def elaborate(self, platform):
        m = Module()

        # Shortcuts.
        interface        = self.interface
        tx_stream        = interface.tx
        new_frame        = interface.tokenizer.new_frame

        targeting_ep_num = (interface.tokenizer.endpoint == self._endpoint_number)
        targeting_us     = targeting_ep_num & interface.tokenizer.is_in
        data_requested   = targeting_us & interface.tokenizer.ready_for_response

        # Track our transmission state.
        bytes_left_in_frame  = Signal.like(self.bytes_in_frame)
        bytes_left_in_packet = Signal(range(0, self._max_packet_size + 1), reset=self._max_packet_size - 1)
        next_data_pid        = Signal(2)
        tx_cnt               = Signal(range(0, self._MAX_FRAME_DATA))
        next_byte            = Signal.like(tx_cnt)

        m.d.comb += [
            tx_stream.payload        .eq(0),
            interface.tx_pid_toggle  .eq(next_data_pid)
        ]

        # Reset our state at the start of each frame.
        with m.If(new_frame):

            m.d.usb += [
                # Latch in how many bytes we'll be transmitting this frame.
                bytes_left_in_frame.eq(self.bytes_in_frame),

                # And start with a full packet to transmit.
                bytes_left_in_packet.eq(self._max_packet_size),
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

        #
        # Core sequencing FSM.
        #
        with m.FSM(domain="usb"):
            m.d.usb += self.frame_finished.eq(0)

            # IDLE -- the host hasn't yet requested data from our endpoint.
            with m.State("IDLE"):
                m.d.comb += next_byte.eq(0)
                m.d.usb  += [
                    tx_cnt.eq(0),
                    tx_stream.first.eq(0),
                ]

                # Once the host requests a packet from us...
                with m.If(data_requested):
                    # If we have data to send, send it.
                    with m.If(bytes_left_in_frame):
                        m.d.usb += tx_stream.first.eq(1)
                        m.next = "SEND_DATA"

                    # Otherwise, we'll send a ZLP.
                    with m.Else():
                        m.next = "SEND_ZLP"

                    # Strobe when a new packet starts.
                    m.d.comb += self.data_requested.eq(1)


            # SEND_DATA -- our primary data-transmission state; handles packet transmission
            with m.State("SEND_DATA"):
                last_byte_in_packet    = (bytes_left_in_packet <= 1)
                last_byte_in_frame     = (bytes_left_in_frame  <= 1)
                byte_terminates_send   = last_byte_in_packet | last_byte_in_frame

                m.d.comb += [
                    # Our data is always valid in this state...
                    tx_stream.valid .eq(1),
                    # ... and we're terminating if we're on the last byte of the packet or frame.
                    tx_stream.last  .eq(byte_terminates_send),
                ]

                # Strobe frame_finished one cycle after we're on the last byte of the frame.
                m.d.usb += self.frame_finished.eq(last_byte_in_frame)

                # Producer has data available.
                with m.If(self.stream.valid):
                    m.d.comb += tx_stream.payload.eq(self.stream.payload)

                # Don't advance ...
                m.d.comb += [
                    next_byte.eq(tx_cnt),
                    self.stream.ready.eq(0),
                ]
                m.d.usb += tx_cnt.eq(next_byte)

                # ... until our data is accepted.
                with m.If(tx_stream.ready):
                    m.d.usb += tx_stream.first.eq(0)

                    # Advance to the next byte in the frame ...
                    m.d.comb += [
                        self.stream.ready.eq(1),
                        next_byte.eq(tx_cnt + 1)
                    ]

                    # ... and mark the relevant byte as sent.
                    m.d.usb += [
                        bytes_left_in_frame   .eq(bytes_left_in_frame  - 1),
                        bytes_left_in_packet  .eq(bytes_left_in_packet - 1),
                    ]

                    # If we've just completed transmitting a packet, or we've
                    # just transmitted a full frame, end our transmission.
                    with m.If(byte_terminates_send):
                        m.d.usb += [
                            # Move to the next DATA pid, which is always one DATA PID less.
                            # [USB2.0: 5.9.2]. We'll reset this back to its maximum value when
                            # the next frame starts.
                            next_data_pid        .eq(next_data_pid - 1),

                            # Mark our next packet as being a full one.
                            bytes_left_in_packet .eq(self._max_packet_size),
                        ]
                        m.next = "IDLE"

            # SEND_ZLP -- sends a zero-length packet, and then return to idle.
            with m.State("SEND_ZLP"):
                # We'll request a ZLP by strobing LAST and VALID without strobing FIRST.
                m.d.comb += [
                    tx_stream.valid  .eq(1),
                    tx_stream.last   .eq(1),
                ]
                m.next = "IDLE"

        return m
