#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Endpoint interfaces for working with streams.

The endpoint interfaces in this module provide endpoint interfaces suitable for
connecting streams to USB endpoints.
"""

from amaranth import *
from usb_protocol.types import USBDirection

from ...stream                import SuperSpeedStreamInterface
from ..protocol.endpoint      import SuperSpeedEndpointInterface


class SuperSpeedStreamInEndpoint(Elaboratable):
    """ Endpoint interface that transmits a simple data stream to a host.

    This interface is suitable for a single bulk or interrupt endpoint.

    This endpoint interface will automatically generate ZLPs when a stream packet would end without
    a short data packet. If the stream's ``last`` signal is tied to zero, then a continuous stream of
    maximum-length-packets will be sent with no inserted ZLPs.

    This implementation is double buffered; and can store a single packet's worth of data while transmitting
    a second packet. Bursting is currently not supported.


    Attributes
    ----------
    stream: SuperSpeedStreamInterface, input stream
        Full-featured stream interface that carries the data we'll transmit to the host.
    interface: SuperSpeedEndpointInterface
        Communications link to our USB device.


    Parameters
    ----------
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    max_packet_size: int
        The maximum packet size for this endpoint. Should match the wMaxPacketSize provided in the
        USB endpoint descriptor.
    """

    SEQUENCE_NUMBER_BITS = 5


    def __init__(self, *, endpoint_number, max_packet_size=1024):
        self._endpoint_number = endpoint_number
        self._max_packet_size = max_packet_size

        #
        # I/O port
        #
        self.stream    = SuperSpeedStreamInterface()
        self.interface = SuperSpeedEndpointInterface()


    def elaborate(self, platform):
        m = Module()

        interface      = self.interface
        handshakes_in  = interface.handshakes_in
        handshakes_out = interface.handshakes_out

        # Parameters for later use.
        data_width     = len(self.stream.data)
        bytes_per_word = data_width // 8
        buffer_depth   = self._max_packet_size // bytes_per_word

        #
        # Transciever sequencing.
        #

        # Keep track of the sequence number used as we're transmitting.
        sequence_number = Signal(self.SEQUENCE_NUMBER_BITS)

        # Create a signal equal to the next sequence number; for easy comparisons.
        next_sequence_number = Signal.like(sequence_number)
        m.d.comb += next_sequence_number.eq(sequence_number + 1)

        # Advance the sequence number after transmission, or reset it when the endpoint is reset.
        advance_sequence = Signal()
        with m.If(interface.ep_reset):
            m.d.ss += sequence_number.eq(0)
        with m.Elif(advance_sequence):
            m.d.ss += sequence_number.eq(next_sequence_number)


        #
        # Transmit buffer.
        #
        # Our USB connection imposed a few requirements on our stream:
        # 1) we must be able to transmit packets at a full rate; i.e. ```valid``
        #    must be asserted from the start to the end of our transfer; and
        # 2) we must be able to re-transmit data if a given packet is not ACK'd.
        #
        # Accordingly, we'll buffer a full USB packet of data, and then transmit
        # it once either a) our buffer is full, or 2) the transfer ends (last=1).
        #
        # This implementation is double buffered; so a buffer fill can be pipelined
        # with a transmit.
        #
        ping_pong_toggle = Signal()

        # We'll create two buffers; so we can fill one as we empty the other.
        # Since each buffer will be used for every other transaction, we'll use a simple flag to identify
        # which of our "ping-pong" buffers is currently being targeted.
        buffer = Array(Memory(width=data_width, depth=buffer_depth, name=f"transmit_buffer_{i}") for i in range(2))
        buffer_write_ports = Array(buffer[i].write_port(domain="ss") for i in range(2))
        buffer_read_ports  = Array(buffer[i].read_port(domain="ss", transparent=False) for i in range(2))

        m.submodules.read_port_0,  m.submodules.read_port_1  = buffer_read_ports
        m.submodules.write_port_0, m.submodules.write_port_1 = buffer_write_ports

        # Create values equivalent to the buffer numbers for our read and write buffer; which switch
        # whenever we swap our two buffers.
        write_buffer_number =  ping_pong_toggle
        read_buffer_number  = ~ping_pong_toggle

        # Create a shorthand that refers to the buffer to be filled; and the buffer to send from.
        # We'll call these the Read and Write buffers.
        buffer_write = buffer_write_ports[write_buffer_number]
        buffer_read  = buffer_read_ports[read_buffer_number]

        # Buffer state tracking:
        # - Our ``fill_count`` keeps track of how much data is stored in a given buffer.
        # - Our ``stream_ended`` bit keeps track of whether the stream ended while filling up
        #   the given buffer. This indicates that the buffer cannot be filled further; and, when
        #   ``generate_zlps`` is enabled, is used to determine if the given buffer should end in
        #   a short packet; which determines whether ZLPs are emitted.
        buffer_fill_count   = Array(Signal(range(0, self._max_packet_size + 1)) for _ in range(2))
        buffer_stream_ended = Array(Signal(name=f"stream_ended_in_buffer{i}") for i in range(2))

        # Create shortcuts to active fill_count / stream_ended signals for the buffer being written.
        write_fill_count   = buffer_fill_count[write_buffer_number]
        write_stream_ended = buffer_stream_ended[write_buffer_number]

        # Create shortcuts to the fill_count / stream_ended signals for the packet being sent.
        read_fill_count   = buffer_fill_count[read_buffer_number]
        read_stream_ended = buffer_stream_ended[read_buffer_number]

        # Keep track of our current send position; which determines where we are in the packet.
        send_position  = Signal(range(0, self._max_packet_size + 1))

        # Shortcut names.
        in_stream  = self.stream
        out_stream = self.interface.tx

        # We're ready to receive data iff we have space in the buffer we're currently filling.
        m.d.comb += [
            in_stream.ready.eq((write_fill_count + 4 <= self._max_packet_size) & ~write_stream_ended),
            buffer_write.en.eq(in_stream.valid.any() & in_stream.ready),
        ]

        # Increment our fill count whenever we accept new data;
        # based on the number of valid bits we have.
        with m.If(buffer_write.en):
            with m.Switch(in_stream.valid):
                with m.Case(0b0001):
                    m.d.ss += write_fill_count.eq(write_fill_count + 1)
                with m.Case(0b0011):
                    m.d.ss += write_fill_count.eq(write_fill_count + 2)
                with m.Case(0b0111):
                    m.d.ss += write_fill_count.eq(write_fill_count + 3)
                with m.Case(0b1111):
                    m.d.ss += write_fill_count.eq(write_fill_count + 4)

        # If the stream ends while we're adding data to the buffer, mark this as an ended stream.
        with m.If(in_stream.last & buffer_write.en):
            m.d.ss += write_stream_ended.eq(1)


        # Use our memory's two ports to capture data from our transfer stream; and two to emit packets
        # into our packet stream. Since we'll never receive to anywhere else, or transmit to anywhere else,
        # we can just unconditionally connect these.
        m.d.comb += [
            # We'll only ever -write- data from our input stream...
            buffer_write_ports[0].data   .eq(in_stream.payload),
            buffer_write_ports[0].addr   .eq(write_fill_count >> 2),
            buffer_write_ports[1].data   .eq(in_stream.payload),
            buffer_write_ports[1].addr   .eq(write_fill_count >> 2),

            # ... and we'll only ever -send- data from the Read buffer; in the SEND_PACKET state.
            buffer_read.addr             .eq(send_position),
        ]


        #
        # Transmit controller.
        #

        # Stores whether the last packet transmitted was a ZLP. This bit of state determines how
        # retranmission behaves.
        last_packet_was_zlp = Signal()

        # Stores whether we'll need to send an ERDY packet before we send any additional data.
        # If we send an NRDY packet indicating that we have no data for the host, the host will
        # stop polling this endpoint until an ERDY packet is sent [USB3.2r1: 8.10.1]. We'll need
        # to send an ERDY packet to have it resume polling.
        erdy_required = Signal()

        # Shortcut for when we need to deal with an in token.
        # Note that, for USB3, an IN token is an ACK that contains a non-zero ``number_of_packets``.
        is_to_us          = (handshakes_in.endpoint_number == self._endpoint_number)
        is_in_token       = (handshakes_in.number_of_packets != 0)
        ack_received      = handshakes_in.ack_received & is_to_us
        in_token_received = ack_received & is_in_token

        with m.FSM(domain='ss'):

            # WAIT_FOR_DATA -- We don't yet have a full packet to transmit, so  we'll capture data
            # to fill the our buffer. At full throughput, this state will never be reached after
            # the initial post-reset fill.
            with m.State("WAIT_FOR_DATA"):

                # We can't yet send data; so we'll send an NRDY transaction packet.
                with m.If(in_token_received):
                    m.d.comb += handshakes_out.send_nrdy  .eq(1)
                    m.d.ss   += erdy_required             .eq(1)

                # If we have valid data that will end our packet, we're no longer waiting for data.
                # We'll now wait for the host to request data from us.
                packet_complete = (write_fill_count + 4 >= self._max_packet_size)
                will_end_packet = packet_complete | in_stream.last

                with m.If(in_stream.valid & will_end_packet):

                    # If we've just finished a packet, we now have data we can send!
                    with m.If(packet_complete | in_stream.last):
                        m.d.ss += [

                            # We're now ready to take the data we've captured and _transmit_ it.
                            # We'll swap our read and write buffers.
                            ping_pong_toggle.eq(~ping_pong_toggle),

                            # Mark our current stream as no longer having ended.
                            read_stream_ended  .eq(0)
                        ]

                        # If we've already sent an NRDY token, we'll need to request an IN token
                        # before the host will be willing to send us one.
                        with m.If(erdy_required | in_token_received):
                            m.next = "REQUEST_IN_TOKEN"

                        # Otherwise, we can wait for an IN token directly.
                        with m.Else():
                            m.next = "WAIT_TO_SEND"


            # REQUEST_IN_TOKEN -- we now have at least a buffer full of data to send; but
            # we've sent a NRDY token to the host; and thus the host is no longer polling for data.
            # We'll send an ERDY token to the host, in order to request it poll us again.
            with m.State("REQUEST_IN_TOKEN"):

                # Send our ERDY token...
                m.d.comb += handshakes_out.send_erdy.eq(1)

                # ... and once that send is complete, move on to waiting for an IN token.
                with m.If(handshakes_out.done):
                    m.next = "WAIT_TO_SEND"


            # WAIT_TO_SEND -- we now have at least a buffer full of data to send; we'll
            # need to wait for an IN token to send it.
            with m.State("WAIT_TO_SEND"):

                # Once we get an IN token, move to sending a packet.
                with m.If(in_token_received):

                    # If we have a packet to send, send it.
                    with m.If(read_fill_count):
                        m.next = "SEND_PACKET"
                        m.d.ss += [
                            last_packet_was_zlp  .eq(0)
                        ]

                    # Otherwise, we entered a transmit path without any data in the buffer.
                    with m.Else():
                        # ... send a ZLP...
                        m.d.comb += interface.tx_zlp.eq(1)

                        # ... and clear the need to follow up with one, since we've just sent a short packet.
                        m.d.ss += [
                            read_stream_ended    .eq(0),
                            last_packet_was_zlp  .eq(1)
                        ]

                        # We've now completed a packet send; so wait for it to be acknowledged.
                        m.next = "WAIT_FOR_ACK"


            # SEND_PACKET -- we now have enough data to send _and_ have received an IN token.
            # We can now send our data over to the host.
            with m.State("SEND_PACKET"):

                m.d.comb += [
                    # Apply our general transfer information.
                    interface.tx_direction        .eq(USBDirection.IN),
                    interface.tx_sequence_number  .eq(sequence_number),
                    interface.tx_length           .eq(read_fill_count),
                    interface.tx_endpoint_number  .eq(self._endpoint_number),
                ]

                with m.If(~out_stream.valid.any() | out_stream.ready):
                    # Once we emitted a word of data for our receiver, move to the next word in our packet.
                    m.d.ss   += send_position     .eq(send_position + 1)
                    m.d.comb += buffer_read.addr  .eq(send_position + 1)

                    # We're on our last word whenever the next word would be contain the end of our data.
                    first_word = (send_position == 0)
                    last_word  = ((send_position + 1) << 2 >= read_fill_count)

                    m.d.ss += [
                        # Block RAM often has a large clock-to-dout delay; register the output to
                        # improve timings.
                        out_stream.payload        .eq(buffer_read.data),

                        # Let our transmitter know the packet boundaries.
                        out_stream.first          .eq(first_word),
                        out_stream.last           .eq(last_word),
                    ]

                    # Figure out which bytes of our stream are valid. Normally; this is all of them,
                    # but the last word is a special case, which we'll have to handle based on how
                    # many bytes we expect to be valid in the word.
                    with m.If(last_word):

                        # We can figure out how many bytes are valid by looking at the last two bits of our
                        # count; which happen to be the mod-4 remainder.
                        with m.Switch(read_fill_count[0:2]):

                            # If we're evenly divisible by four, all four bytes are valid.
                            with m.Case(0):
                                m.d.ss += out_stream.valid.eq(0b1111)

                            # Otherwise, our remainder tells os how many bytes are valid.
                            with m.Case(1):
                                m.d.ss += out_stream.valid.eq(0b0001)
                            with m.Case(2):
                                m.d.ss += out_stream.valid.eq(0b0011)
                            with m.Case(3):
                                m.d.ss += out_stream.valid.eq(0b0111)


                    # For every word that's not the last one, we know that all bytes are valid.
                    with m.Else():
                        m.d.ss += out_stream.valid.eq(0b1111)

                    # If we've just sent our last word, we're now ready to wait for a response
                    # from our host.
                    with m.If(last_word):
                        m.next = 'WAIT_FOR_ACK'


            # WAIT_FOR_ACK -- We've just sent a packet; but don't know if the host has
            # received it correctly. We'll wait to see if the host ACKs.
            with m.State("WAIT_FOR_ACK"):

                # We're done transmitting data.
                m.d.ss   += out_stream.valid.eq(0)

                # Reset our send-position for the next data packet.
                m.d.ss   += send_position   .eq(0)
                m.d.comb += buffer_read.addr.eq(0)

                # In USB3, an ACK handshake can act as an ACK, an error indicator, and/or an IN token.
                # This helps to maximize bus bandwidth, but means we have to handle each case carefully.
                with m.If(ack_received):

                    # Figure out how the sequence advertisement in our ACK relates to our current sequence number.
                    sequence_advancing = (handshakes_in.next_sequence == next_sequence_number)

                    # Our simplest case is actually when an error occurs, which is indicated by receiving
                    # an ACK packet with Retry set to `1`. For now, we'll also treat a repeated sequence number
                    # as an indication that we need to re-try the given packet.
                    with m.If(handshakes_in.retry_required | ~sequence_advancing):

                        # In this case, we'll re-transmit the relevant data, either by sending another ZLP...
                        with m.If(last_packet_was_zlp):
                            m.d.comb += [
                                interface.tx_zlp.eq(1),
                                advance_sequence.eq(1),
                            ]

                        # ... or by moving right back into sending a data packet.
                        with m.Else():
                            m.next = 'SEND_PACKET'


                    # Otherwise, if our ACK contains the next sequence number, then this is an acknowledgement
                    # of the previous packet [USB3.2r1: 8.12.1.2].
                    with m.Else():

                        # We no longer need to keep the data that's been acknowledged; clear it.
                        m.d.ss += read_fill_count.eq(0)

                        # Figure out if we'll need to follow up with a ZLP. If we have ZLP generation enabled,
                        # we'll make sure we end on a short packet. If this is max-packet-size packet _and_ our
                        # transfer ended with this packet; we'll need to inject a ZLP.
                        follow_up_with_zlp = \
                            (read_fill_count == self._max_packet_size) & read_stream_ended

                        # If we're following up with a ZLP, we have two cases, depending on whether this ACK
                        # is also requesting another packet.
                        with m.If(follow_up_with_zlp):

                            # If we are requesting another packet immediately, we can said ZLP our immediately,
                            # and then continue waiting for the next ACK.
                            with m.If(is_in_token):

                                # ... send a ZLP...
                                m.d.comb += [
                                    interface.tx_zlp.eq(1),
                                    advance_sequence.eq(1),
                                ]

                                # ... and clear the need to follow up with one, since we've just sent a short packet.
                                m.d.ss += [
                                    read_stream_ended    .eq(0),
                                    last_packet_was_zlp  .eq(1)
                                ]

                            # Otherwise, we'll wait for an attempt to send data before we generate a ZLP.
                            with m.Else():
                                m.next = "WAIT_TO_SEND"


                        # Otherwise, there's a possibility we already have a packet-worth of data waiting
                        # for us in our "write buffer", which we've been filling in the background.
                        # If this is the case, we'll flip which buffer we're working with, and then
                        # ready ourselves for transmit.
                        packet_completing = in_stream.valid & (write_fill_count + 4 >= self._max_packet_size)
                        with m.Elif(~in_stream.ready | packet_completing):
                            m.d.comb += [
                                advance_sequence   .eq(1),
                            ]
                            m.d.ss += [
                                ping_pong_toggle   .eq(~ping_pong_toggle),
                                read_stream_ended  .eq(0),
                            ]

                            with m.If(is_in_token):
                                m.d.ss += [
                                    last_packet_was_zlp  .eq(0)
                                ]
                                m.next = "SEND_PACKET"

                            with m.Else():
                                m.next = "WAIT_TO_SEND"

                        # If neither of the above conditions are true; we now don't have enough data to send.
                        # We'll wait for enough data to transmit.
                        with m.Else():
                            m.next = "WAIT_FOR_DATA"

        return m
