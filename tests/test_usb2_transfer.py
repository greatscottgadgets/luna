#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test          import LunaGatewareTestCase, usb_domain_test_case

from luna.gateware.usb.usb2.transfer import USBInTransferManager

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


    @usb_domain_test_case
    def test_discard(self):
        dut = self.dut

        packet_stream   = dut.packet_stream
        transfer_stream = dut.transfer_stream

        # Before we do anything, we shouldn't have anything our output stream.
        self.assertEqual((yield packet_stream.valid), 0)

        # Our transfer stream should accept data until we fill up its buffers.
        self.assertEqual((yield transfer_stream.ready), 1)

        # We queue up two full packets.
        yield transfer_stream.valid.eq(1)
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            yield transfer_stream.payload.eq(value)
            yield

        for value in [0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00]:
            yield transfer_stream.payload.eq(value)
            yield
        yield transfer_stream.valid.eq(0)

        # Once we do see an IN token...
        yield from self.pulse(dut.tokenizer.ready_for_response)

        # ... we should start transmitting...
        self.assertEqual((yield packet_stream.valid), 1)

        # ... and should see the full packet be emitted...
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            self.assertEqual((yield packet_stream.payload), value)
            yield

        # ... with DATA PID 0 ...
        self.assertEqual((yield dut.data_pid), 0)

        # ... and then the packet should end.
        self.assertEqual((yield packet_stream.valid), 0)

        # If we ACK the first packet...
        yield from self.pulse(dut.handshakes_in.ack)

        # ... we should be ready to accept data again.
        self.assertEqual((yield transfer_stream.ready), 1)
        yield from self.advance_cycles(5)

        # If we then discard the second packet...
        yield from self.pulse(dut.discard, step_after=False)

        # ... we shouldn't see a transmit request upon an in token.
        yield from self.pulse(dut.tokenizer.ready_for_response, step_after=False)
        yield from self.advance_cycles(5)
        self.assertEqual((yield packet_stream.valid), 0)

        # If we send another full packet...
        yield transfer_stream.valid.eq(1)
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            yield transfer_stream.payload.eq(value)
            yield
        yield transfer_stream.valid.eq(0)

        # ... and see an IN token...
        yield from self.pulse(dut.tokenizer.ready_for_response)

        # ... we should start transmitting...
        self.assertEqual((yield packet_stream.valid), 1)

        # ... add should see the full packet be emitted...
        for value in [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]:
            self.assertEqual((yield packet_stream.payload), value)
            yield

        # ... with the correct DATA PID.
        self.assertEqual((yield dut.data_pid), 1)
