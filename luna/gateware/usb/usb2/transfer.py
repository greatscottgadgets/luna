#
# This file is part of LUNA.
#
"""
This module contains gateware designed to assist with endpoint/transfer state management.
Its components facilitate data transfer longer than a single packet.
"""

import unittest

from nmigen         import Signal, Elaboratable, Module
from nmigen.hdl.mem import Memory

from .packet        import HandshakeExchangeInterface, TokenDetectorInterface
from ..stream       import USBInStreamInterface
from ...stream      import StreamInterface

from ...test        import LunaGatewareTestCase, usb_domain_test_case

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
        self.data_pid         = Signal(2)

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

        # Track whether we should follow up our current packet with a ZLP.
        follow_up_with_zlp = Signal()

        # Handle our PID-sequence reset.
        with m.If(self.reset_sequence):
            m.d.usb += self.data_pid.eq(self.start_with_data1)

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
        # For now, we'll assume that data can be filled between packets without limiting
        # speed -- but it may be wise to set up a ping/pong pair of packet buffers.
        #
        buffer = Memory(width=8, depth=self._max_packet_size, name="transmit_buffer")
        m.submodules.buffer_write = buffer_write = buffer.write_port(domain="usb")
        m.submodules.buffer_read  = buffer_read  = buffer.read_port(domain="usb")

        # Keep track of where we are in our read/write positions.
        fill_count    = Signal(range(0, self._max_packet_size + 1))
        send_position = Signal(range(0, self._max_packet_size + 1))

        in_stream  = self.transfer_stream
        out_stream = self.packet_stream

        # Use our memory's two ports to capture data from our transfer stream;
        # and two emit packets into our packet stream. Since we'll never receive
        # anywhere else, or transmit to anywhere else, we can just unconditionally
        # connect these.
        m.d.comb += [
            buffer_write.data   .eq(in_stream.payload),
            buffer_write.addr   .eq(fill_count),

            buffer_read.addr    .eq(send_position),
            out_stream.payload  .eq(buffer_read.data),
        ]

        # Shortcut for when we need to deal with an in token.
        # Pulses high an interpacket delay after receiving an IN token.
        in_token_received = self.active & self.tokenizer.is_in & self.tokenizer.ready_for_response

        with m.FSM(domain='usb'):

            # FILLING_BUFFER -- we don't yet have a full packet to transmit, so
            # we'll capture data to fill the buffer until we either do, or the transfer ends
            with m.State("FILLING_BUFFER"):
                m.d.comb += [
                    # We're always ready to receive data, since we're
                    # just sticking it into our buffer.
                    in_stream.ready.eq(1),

                    # We can't yet send data; so NAK any packet requests.
                    self.handshakes_out.nak.eq(in_token_received),
                ]

                # If we have valid data, enqueue it.
                with m.If(in_stream.valid):
                    m.d.comb += buffer_write.en.eq(1)
                    m.d.usb  += fill_count.eq(fill_count + 1)

                    # If we've just finished a packet, send our data.
                    packet_complete = (fill_count + 1 == self._max_packet_size)
                    with m.If(packet_complete | in_stream.last):
                        m.next = "WAIT_FOR_TOKEN"

                        # If we've finished our stream -and- we've just filled up a packet, we're not ending
                        # on a short packet. If ZLP generation is enabled, we'll want to follow up with a ZLP.
                        ends_without_short_packet = packet_complete & in_stream.last
                        m.d.usb += follow_up_with_zlp.eq(ends_without_short_packet & self.generate_zlps)


            # WAIT_FOR_TOKEN -- we now have a buffer full of data to send; we'll
            # need to wait for an IN token to send it.
            with m.State("WAIT_FOR_TOKEN"):
                m.d.usb += send_position .eq(0),

                # Once we get an IN token, move to sending a packet.
                with m.If(in_token_received):

                    # If we have a packet to send, send it.
                    with m.If(fill_count):
                        m.next = "SEND_PACKET"
                        m.d.usb += out_stream.first  .eq(1)

                    # Otherwise, we entered a transmit path without any data in the buffer.
                    with m.Else():
                        m.next = "WAIT_FOR_ACK"


            # SEND_PACKET -- we're now ready for us to
            with m.State("SEND_PACKET"):
                last_packet = (send_position + 1 == fill_count)

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
                    m.d.usb += [
                        # ... clear the data we've sent from our buffer...
                        fill_count.eq(0),

                        # ... toggle our DATA pid...
                        self.data_pid[0].eq(~self.data_pid[0])
                    ]

                    # ... and either send a ZLP if required or move back to idle.
                    with m.If(follow_up_with_zlp):
                        m.next = "WAIT_FOR_TOKEN"
                    with m.Else():
                        m.next = "FILLING_BUFFER"

                # If the host starts a new packet without ACK'ing, we'll need to retransmit.
                # We'll move back to our "wait for token" state without clearing our buffer.
                with m.If(self.tokenizer.new_token):
                    m.next = "WAIT_FOR_TOKEN"

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

        # Before we do anything, we should start with a DATA0 pid; and
        # we shouldn't have anything on our output stream.
        self.assertEqual((yield dut.data_pid), 0)
        self.assertEqual((yield packet_stream.valid), 0)

        # Our transfer stream should accept data until we provide it a full packet.
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

        # ... we should stop accepting data...
        yield
        self.assertEqual((yield transfer_stream.ready), 0)

        # ... but we shouldn't see a transmit request until we receive an IN token.
        self.assertEqual((yield packet_stream.valid), 0)
        yield from self.advance_cycles(5)
        self.assertEqual((yield packet_stream.valid), 0)

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

        # ... we should see our DATA PID flip, and we should be ready to accept data again.
        yield self.assertEqual((yield dut.data_pid), 1)
        yield self.assertEqual((yield transfer_stream.ready), 1)


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

if __name__ == "__main__":
    unittest.main()
