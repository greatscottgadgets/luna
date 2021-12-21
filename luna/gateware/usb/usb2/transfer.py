#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

"""
This module contains gateware designed to assist with endpoint/transfer state management.
Its components facilitate data transfer longer than a single packet.
"""

import unittest

from amaranth         import Signal, Elaboratable, Module, Array
from amaranth.hdl.mem import Memory

from .packet          import HandshakeExchangeInterface, TokenDetectorInterface
from ..stream         import USBInStreamInterface
from ...stream        import StreamInterface

from ...test          import LunaGatewareTestCase, usb_domain_test_case

class USBInTransferManager(Elaboratable):
    """ Sequencer that converts a long data stream (a USB *transfer*) into a burst of USB packets.

    This module is designed so it can serve as the core of a IN endpoint.

    Attributes
    ----------

    active: Signal(), input
        Held high to enable this module to send packets to the host, and interpret tokens from the host.
        This is typically equivalent to the relevant endpoint being addressed by the host.

    transfer_stream: StreamInterface, input stream
        Input stream; accepts transfer data to be sent on the endpoint. This stream represents
        a USB transfer, and can be as long as is desired; and will be sent in max-packet-size chunks.

        For this stream: ``first`` is ignored; and thus entirely optional. ``last`` is optional;
        if it is not provided; this module will send only max-length-packets, sending a new packet
        every time a full packet size is reached.
    packet_stream: USBInStreamInterface, output stream
        Output stream; broken into packets to be sent.

    data_pid: Signal(2), output
        The LSBs of the data PID to be issued with the current packet. Used with :attr:`packet_stream`
        to indicate the PID of the transmitted packet.

    tokenizer: TokenDetectorInterface, input
        Connection to a detector that detects incoming tokens packets.

    handshakes_in: HandshakeExchangeInterface, input
        Indicates when handshakes are received from the host.
    handshakes_out: HandshakeExchangeInterface, output
        Output that carries handshake packet requests.

    generate_zlps: Signal(), input
        If high, zero-length packets will automatically be generated if the end of a transfer would
        not result in a short packet. (This should be set for control endpoints; and for any interface
        where transfer boundaries are significant.)

    start_with_data1: Signal(), input
        If high, the transmitter will start our PID with DATA1
    reset_sequence: Signal(), input
        If true, our PID generated will reset to the value indicated by `start_with_data1`.
        If desired, this can be held permanently high to control our PID expectation manually.

    Parameters
    ----------
    max_packet_size: int
        The maximum packet size for our associated endpoint, in bytes.
    """

    def __init__(self, max_packet_size):

        self._max_packet_size = max_packet_size

        #
        # I/O port
        #
        self.active           = Signal()

        self.transfer_stream  = StreamInterface()
        self.packet_stream    = USBInStreamInterface()

        # Note: we'll start with DATA1 in our register; as we'll toggle our data PID
        # before we send.
        self.data_pid         = Signal(2, reset=1)
        self.buffer_toggle    = Signal()

        self.tokenizer        = TokenDetectorInterface()
        self.handshakes_in    = HandshakeExchangeInterface(is_detector=True)
        self.handshakes_out   = HandshakeExchangeInterface(is_detector=False)

        self.generate_zlps    = Signal()
        self.start_with_data1 = Signal()
        self.reset_sequence   = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Transciever state.
        #


        # Handle our PID-sequence reset.
        # Note that we store the _inverse_ of our data PID, as we'll toggle our DATA PID
        # before sending.
        with m.If(self.reset_sequence):
            m.d.usb += self.data_pid.eq(~self.start_with_data1)

        #
        # Transmit buffer.
        #
        # Our USB connection imposed a few requirements on our stream:
        # 1) we must be able to transmit packets at a full rate; i.e.
        #    must be asserted from the start to the end of our transfer; and
        # 2) we must be able to re-transmit data if a given packet is not ACK'd.
        #
        # Accordingly, we'll buffer a full USB packet of data, and then transmit
        # it once either a) our buffer is full, or 2) the transfer ends (last=1).
        #
        # This implementation is double buffered; so a buffer fill can be pipelined
        # with a transmit.
        #

        # We'll create two buffers; so we can fill one as we empty the other.
        buffer = Array(Memory(width=8, depth=self._max_packet_size, name=f"transmit_buffer_{i}") for i in range(2))
        buffer_write_ports = Array(buffer[i].write_port(domain="usb") for i in range(2))
        buffer_read_ports  = Array(buffer[i].read_port(domain="usb") for i in range(2))

        m.submodules.read_port_0,  m.submodules.read_port_1  = buffer_read_ports
        m.submodules.write_port_0, m.submodules.write_port_1 = buffer_write_ports

        # Create values equivalent to the buffer numbers for our read and write buffer; which switch
        # whenever we swap our two buffers.
        write_buffer_number =  self.buffer_toggle
        read_buffer_number  = ~self.buffer_toggle

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
        send_position = Signal(range(0, self._max_packet_size + 1))

        # Shortcut names.
        in_stream  = self.transfer_stream
        out_stream = self.packet_stream


        # Use our memory's two ports to capture data from our transfer stream; and two emit packets
        # into our packet stream. Since we'll never receive to anywhere else, or transmit to anywhere else,
        # we can just unconditionally connect these.
        m.d.comb += [

            # We'll only ever -write- data from our input stream...
            buffer_write_ports[0].data   .eq(in_stream.payload),
            buffer_write_ports[0].addr   .eq(write_fill_count),
            buffer_write_ports[1].data   .eq(in_stream.payload),
            buffer_write_ports[1].addr   .eq(write_fill_count),

            # ... and we'll only ever -send- data from the Read buffer.
            buffer_read.addr             .eq(send_position),
            out_stream.payload           .eq(buffer_read.data),

            # We're ready to receive data iff we have space in the buffer we're currently filling.
            in_stream.ready              .eq((write_fill_count != self._max_packet_size) & ~write_stream_ended),
            buffer_write.en              .eq(in_stream.valid & in_stream.ready)
        ]

        # Increment our fill count whenever we accept new data.
        with m.If(buffer_write.en):
            m.d.usb += write_fill_count.eq(write_fill_count + 1)

        # If the stream ends while we're adding data to the buffer, mark this as an ended stream.
        with m.If(in_stream.last & buffer_write.en):
            m.d.usb += write_stream_ended.eq(1)


        # Shortcut for when we need to deal with an in token.
        # Pulses high an interpacket delay after receiving an IN token.
        in_token_received = self.active & self.tokenizer.is_in & self.tokenizer.ready_for_response

        with m.FSM(domain='usb'):

            # WAIT_FOR_DATA -- We don't yet have a full packet to transmit, so  we'll capture data
            # to fill the our buffer. At full throughput, this state will never be reached after
            # the initial post-reset fill.
            with m.State("WAIT_FOR_DATA"):

                # We can't yet send data; so NAK any packet requests.
                m.d.comb += self.handshakes_out.nak.eq(in_token_received)

                # If we have valid data that will end our packet, we're no longer waiting for data.
                # We'll now wait for the host to request data from us.
                packet_complete = (write_fill_count + 1 == self._max_packet_size)
                will_end_packet = packet_complete | in_stream.last

                with m.If(in_stream.valid & will_end_packet):

                    # If we've just finished a packet, we now have data we can send!
                    with m.If(packet_complete | in_stream.last):
                        m.next = "WAIT_TO_SEND"
                        m.d.usb += [

                            # We're now ready to take the data we've captured and _transmit_ it.
                            # We'll swap our read and write buffers, and toggle our data PID.
                            self.buffer_toggle  .eq(~self.buffer_toggle),
                            self.data_pid[0]    .eq(~self.data_pid[0]),

                            # Mark our current stream as no longer having ended.
                            read_stream_ended  .eq(0)
                        ]


            # WAIT_TO_SEND -- we now have at least a buffer full of data to send; we'll
            # need to wait for an IN token to send it.
            with m.State("WAIT_TO_SEND"):
                m.d.usb += send_position .eq(0),

                # Once we get an IN token, move to sending a packet.
                with m.If(in_token_received):

                    # If we have a packet to send, send it.
                    with m.If(read_fill_count):
                        m.next = "SEND_PACKET"
                        m.d.usb += out_stream.first  .eq(1)

                    # Otherwise, we entered a transmit path without any data in the buffer.
                    with m.Else():
                        m.d.comb += [
                            # Send a ZLP...
                            out_stream.valid  .eq(1),
                            out_stream.last   .eq(1),
                        ]
                        # ... and clear the need to follow up with one, since we've just sent a short packet.
                        m.d.usb += read_stream_ended.eq(0)
                        m.next = "WAIT_FOR_ACK"


            with m.State("SEND_PACKET"):
                last_packet = (send_position + 1 == read_fill_count)

                m.d.comb += [
                    # We're always going to be sending valid data, since data is always
                    # available from our memory.
                    out_stream.valid  .eq(1),

                    # Let our transmitter know when we've reached our last packet.
                    out_stream.last   .eq(last_packet)
                ]

                # Once our transmitter accepts our data...
                with m.If(out_stream.ready):

                    m.d.usb += [
                        # ... move to the next byte in our packet ...
                        send_position     .eq(send_position + 1),

                        # ... and mark our packet as no longer the first.
                        out_stream.first  .eq(0)
                    ]

                    # Move our memory pointer to its next position.
                    m.d.comb += buffer_read.addr  .eq(send_position + 1),

                    # If we've just sent our last packet, we're now ready to wait for a
                    # response from our host.
                    with m.If(last_packet):
                        m.next = 'WAIT_FOR_ACK'


            # WAIT_FOR_ACK -- We've just sent a packet; but don't know if the host has
            # received it correctly. We'll wait to see if the host ACKs.
            with m.State("WAIT_FOR_ACK"):

                # If the host does ACK...
                with m.If(self.handshakes_in.ack):
                    # ... clear the data we've sent from our buffer.
                    m.d.usb += read_fill_count.eq(0)

                    # Figure out if we'll need to follow up with a ZLP. If we have ZLP generation enabled,
                    # we'll make sure we end on a short packet. If this is max-packet-size packet _and_ our
                    # transfer ended with this packet; we'll need to inject a ZLP.
                    follow_up_with_zlp = \
                        self.generate_zlps & (read_fill_count == self._max_packet_size) & read_stream_ended

                    # If we're following up with a ZLP, move back to our "wait to send" state.
                    # Since we've now cleared our fill count; this next go-around will emit a ZLP.
                    with m.If(follow_up_with_zlp):
                        m.d.usb += self.data_pid[0].eq(~self.data_pid[0]),
                        m.next = "WAIT_TO_SEND"

                    # Otherwise, there's a possibility we already have a packet-worth of data waiting
                    # for us in our "write buffer", which we've been filling in the background.
                    # If this is the case, we'll flip which buffer we're working with, toggle our data pid,
                    # and then ready ourselves for transmit.
                    packet_completing = in_stream.valid & ((write_fill_count + 1 == self._max_packet_size) | in_stream.last)
                    with m.Elif(~in_stream.ready | packet_completing):
                        m.next = "WAIT_TO_SEND"
                        m.d.usb += [
                            self.buffer_toggle .eq(~self.buffer_toggle),
                            self.data_pid[0]   .eq(~self.data_pid[0]),
                            read_stream_ended  .eq(0)
                        ]

                    # If neither of the above conditions are true; we now don't have enough data to send.
                    # We'll wait for enough data to transmit.
                    with m.Else():
                        m.next = "WAIT_FOR_DATA"


                # If the host starts a new packet without ACK'ing, we'll need to retransmit.
                # We'll move back to our "wait for token" state without clearing our buffer.
                with m.If(self.tokenizer.new_token):
                    m.next = 'WAIT_TO_SEND'

        return m


class USBInTransferManagerTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = USBInTransferManager
    FRAGMENT_ARGUMENTS  = {"max_packet_size": 8}

    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY = 60e6

    def initialize_signals(self):

        # By default, pretend our transmitter is always accepting data...
        yield self.dut.packet_stream.ready.eq(1)

        # And pretend that our host is always tagreting our endpoint.
        yield self.dut.active.eq(1)
        yield self.dut.tokenizer.is_in.eq(1)


    @usb_domain_test_case
    def test_normal_transfer(self):
        dut = self.dut

        packet_stream   = dut.packet_stream
        transfer_stream = dut.transfer_stream

        # Before we do anything, we shouldn't have anything our output stream.
        self.assertEqual((yield packet_stream.valid), 0)

        # Our transfer stream should accept data until we fill up its buffers.
        self.assertEqual((yield transfer_stream.ready), 1)

        # Once we start sending data to our packetizer...
        yield transfer_stream.valid.eq(1)
        yield transfer_stream.payload.eq(0x11)
        yield

        # We still shouldn't see our packet stream start transmitting;
        # and we should still be accepting data.
        self.assertEqual((yield packet_stream.valid), 0)
        self.assertEqual((yield transfer_stream.ready), 1)

        # Once we see a full packet...
        for value in [0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            yield transfer_stream.payload.eq(value)
            yield
        yield transfer_stream.valid.eq(0)

        # ... we shouldn't see a transmit request until we receive an IN token.
        self.assertEqual((yield transfer_stream.ready), 1)
        yield from self.advance_cycles(5)
        self.assertEqual((yield packet_stream.valid), 0)

        # We -should-, however, keep filling our secondary buffer while waiting.
        yield transfer_stream.valid.eq(1)
        self.assertEqual((yield transfer_stream.ready), 1)
        for value in [0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00]:
            yield transfer_stream.payload.eq(value)
            yield

        # Once we've filled up -both- buffers, our data should no longer be ready.
        yield
        self.assertEqual((yield transfer_stream.ready), 0)

        # Once we do see an IN token...
        yield from self.pulse(dut.tokenizer.ready_for_response)

        # ... we should start transmitting...
        self.assertEqual((yield packet_stream.valid), 1)

        # ... we should see the full packet be emitted...
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            self.assertEqual((yield packet_stream.payload), value)
            yield

        # ... and then the packet should end.
        self.assertEqual((yield packet_stream.valid), 0)

        # We should now be waiting for an ACK. While waiting, we still need
        # to keep the last packet; so we'll expect that we're not ready for data.
        self.assertEqual((yield transfer_stream.ready), 0)

        # If we receive anything other than an ACK...
        yield from self.pulse(dut.tokenizer.new_token)
        yield

        # ... we should see the same data transmitted again, with the same PID.
        yield from self.pulse(dut.tokenizer.ready_for_response, step_after=False)
        yield self.assertEqual((yield dut.data_pid), 0)

        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            self.assertEqual((yield packet_stream.payload), value)
            yield

        # If we do ACK...
        yield from self.pulse(dut.handshakes_in.ack)

        # ... we should see our DATA PID flip, and we should be ready to accept data again...
        yield self.assertEqual((yield dut.data_pid), 1)
        yield self.assertEqual((yield transfer_stream.ready), 1)

        #  ... and we should get our second packet.
        yield from self.pulse(dut.tokenizer.ready_for_response, step_after=True)
        for value in [0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00]:
            self.assertEqual((yield packet_stream.payload), value)
            yield


    @usb_domain_test_case
    def test_nak_when_not_ready(self):
        dut = self.dut

        # We shouldn't initially be NAK'ing anything...
        self.assertEqual((yield dut.handshakes_out.nak), 0)

        # ... but if we get an IN token we're not ready for...
        yield from self.pulse(dut.tokenizer.ready_for_response, step_after=False)

        # ... we should see one cycle of NAK.
        self.assertEqual((yield dut.handshakes_out.nak), 1)
        yield
        self.assertEqual((yield dut.handshakes_out.nak), 0)


    @usb_domain_test_case
    def test_zlp_generation(self):
        dut = self.dut

        packet_stream   = dut.packet_stream
        transfer_stream = dut.transfer_stream

        # Simulate a case where we're generating ZLPs.
        yield dut.generate_zlps.eq(1)


        # If we're sent a full packet _without the transfer stream ending_...
        yield transfer_stream.valid.eq(1)
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            yield transfer_stream.payload.eq(value)
            yield
        yield transfer_stream.valid.eq(0)


        # ... we should receive that data packet without a ZLP.
        yield from self.pulse(dut.tokenizer.ready_for_response)
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            self.assertEqual((yield packet_stream.payload), value)
            yield
        self.assertEqual((yield dut.data_pid), 0)
        yield from self.pulse(dut.handshakes_in.ack)


        # If we send a full packet...
        yield transfer_stream.valid.eq(1)
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77]:
            yield transfer_stream.payload.eq(value)
            yield

        # ... that _ends_ our transfer...
        yield transfer_stream.payload.eq(0x88)
        yield transfer_stream.last.eq(1)
        yield

        yield transfer_stream.last.eq(0)
        yield transfer_stream.valid.eq(0)

        # ... we should emit the relevant data packet...
        yield from self.pulse(dut.tokenizer.ready_for_response)
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            self.assertEqual((yield packet_stream.payload), value)
            yield
        self.assertEqual((yield dut.data_pid), 1)
        yield from self.pulse(dut.handshakes_in.ack)

        # ... followed by a ZLP.
        yield from self.pulse(dut.tokenizer.ready_for_response, step_after=False)
        self.assertEqual((yield packet_stream.last), 1)
        self.assertEqual((yield dut.data_pid), 0)
        yield from self.pulse(dut.handshakes_in.ack)


        # Finally, if we're sent a short packet that ends our stream...
        yield transfer_stream.valid.eq(1)
        for value in [0xAA, 0xBB, 0xCC]:
            yield transfer_stream.payload.eq(value)
            yield
        yield transfer_stream.payload.eq(0xDD)
        yield transfer_stream.last.eq(1)

        yield
        yield transfer_stream.last.eq(0)
        yield transfer_stream.valid.eq(0)

        # ... we should emit the relevant short packet...
        yield from self.pulse(dut.tokenizer.ready_for_response)
        for value in [0xAA, 0xBB, 0xCC, 0xDD]:
            self.assertEqual((yield packet_stream.payload), value)
            yield
        yield from self.pulse(dut.handshakes_in.ack)
        self.assertEqual((yield dut.data_pid), 1)


        # ... and we shouldn't emit a ZLP; meaning we should be ready to receive new data.
        self.assertEqual((yield transfer_stream.ready), 1)


if __name__ == "__main__":
    unittest.main()
