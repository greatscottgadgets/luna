#
# This file is part of LUNA.
#
# Copyright (c) 2025 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from luna.gateware.test  import (
    LunaUSBGatewareTestCase,
    usb_domain_test_case,
)

from luna.usb2           import (
    USBIsochronousStreamInEndpoint,
    USBIsochronousStreamOutEndpoint,
)


MAX_PACKET_SIZE = 512

class USBIsochronousStreamInEndpointTest(LunaUSBGatewareTestCase):
    FRAGMENT_UNDER_TEST = USBIsochronousStreamInEndpoint
    FRAGMENT_ARGUMENTS  = {'endpoint_number': 1, 'max_packet_size': MAX_PACKET_SIZE}

    def initialize_signals(self):
        # Configure the endpoint.
        yield self.dut.bytes_in_frame.eq(MAX_PACKET_SIZE)

        # Pretend that our host is always targeting our endpoint.
        yield self.dut.interface.tokenizer.endpoint.eq(self.dut._endpoint_number)
        yield self.dut.interface.tokenizer.is_in.eq(1)

    @usb_domain_test_case
    def test_single_packet_in(self):
        dut = self.dut

        producer = dut.stream
        consumer = dut.interface.tx
        data     = [b % 0xff for b in range(1, MAX_PACKET_SIZE + 1)]
        sent     = []

        # Before we see any data, our streams should all be invalid
        self.assertEqual((yield consumer.first), 0)
        self.assertEqual((yield consumer.last), 0)
        self.assertEqual((yield consumer.payload), 0)
        self.assertEqual((yield consumer.ready), 0)
        self.assertEqual((yield consumer.valid), 0)
        self.assertEqual((yield producer.payload), 0)
        self.assertEqual((yield producer.ready), 0)
        self.assertEqual((yield producer.valid), 0)

        # Once we start a new frame ...
        yield dut.interface.tokenizer.new_frame.eq(1)
        yield

        # ... but the host hasn't yet requested data from our endpoint;
        # our stream should still be at rest.
        self.assertEqual((yield consumer.first), 0)
        self.assertEqual((yield dut.data_requested), 0)

        # When the host requests data ...
        yield dut.interface.tokenizer.ready_for_response.eq(1)
        yield

        # ... we go out of State(IDLE) and can check that data_requested is strobed.
        self.assertEqual((yield dut.data_requested), 1)

        # Then one cycle later...
        yield

        # ... we will be in State(SEND_DATA) and our consumer stream becomes valid.
        self.assertEqual((yield consumer.first), 1)
        self.assertEqual((yield consumer.last), 0)
        self.assertEqual((yield consumer.valid), 1)

        # Once the producer has data available ...
        yield producer.valid.eq(1)
        yield producer.payload.eq(data[0])

        # ... but we haven't advanced yet ...
        self.assertEqual((yield producer.ready), 0)
        self.assertEqual((yield consumer.ready), 0)
        self.assertEqual((yield consumer.payload), 0x00)

        # ... until our data is accepted.
        yield consumer.ready.eq(1)
        yield
        sent.append((yield consumer.payload))

        # Now we can chack that the transmitter has the first byte ...
        self.assertEqual((yield producer.ready), 1)
        self.assertEqual((yield consumer.payload), data[0])
        self.assertEqual((yield consumer.first), 1)

        # ... before sending the rest of the packet.
        clocks = 0
        for byte in data[1:]:
            clocks += 1
            yield producer.payload.eq(byte)
            yield
            sent.append((yield consumer.payload))
            self.assertEqual((yield consumer.payload), byte)

        # Finally, we can check that we have received the correct
        # amount of data and that this was the last byte.
        self.assertEqual(sent, data)
        self.assertEqual((yield consumer.last), 1)
        self.assertEqual(clocks, len(data) - 1)


class USBIsochronousStreamOutEndpointTest(LunaUSBGatewareTestCase):
    FRAGMENT_UNDER_TEST = USBIsochronousStreamOutEndpoint
    FRAGMENT_ARGUMENTS  = {'endpoint_number': 1, 'max_packet_size': MAX_PACKET_SIZE}

    def initialize_signals(self):
        # Pretend that our host is always targeting our endpoint.
        yield self.dut.interface.tokenizer.endpoint.eq(self.dut._endpoint_number)
        yield self.dut.interface.tokenizer.is_out.eq(1)


    @usb_domain_test_case
    def test_single_packet_out(self):
        dut = self.dut

        producer = dut.interface.rx
        consumer = dut.stream
        data     = [b % 0xff for b in range(1, MAX_PACKET_SIZE + 1)]
        received = []

        # Before we see any data, our streams should all be invalid.
        self.assertEqual((yield consumer.p.data), 0)
        self.assertEqual((yield consumer.p.first), 0)
        self.assertEqual((yield consumer.p.last), 0)
        self.assertEqual((yield consumer.ready), 0)
        self.assertEqual((yield consumer.valid), 0)
        self.assertEqual((yield producer.next), 0)
        self.assertEqual((yield producer.payload), 0)
        self.assertEqual((yield producer.valid), 0)

        # Once the producer sends the first byte ...
        yield producer.valid.eq(1)
        yield producer.next.eq(1)
        yield producer.payload.eq(data[0])
        yield

        # ... and only the first byte ...
        yield producer.next.eq(0)
        yield

        # ... we shouldn't see anything in the consumer stream ...
        self.assertEqual((yield consumer.p.first), 0)
        self.assertEqual((yield consumer.p.last), 0)
        self.assertEqual((yield consumer.p.data), 0)

        # ... but even if we were to mark the consumer's stream as ready ...
        yield consumer.ready.eq(1)
        yield

        # ... the consumer stream will still not be valid because
        # we're using a TransactionalizedFIFO that will only commit
        # once the entire packet has been received.
        self.assertEqual((yield consumer.valid), 0)
        self.assertEqual((yield consumer.p.first), 0)
        self.assertEqual((yield consumer.p.last), 0)
        self.assertEqual((yield consumer.p.data), 0)

        # So let's send the rest of the packet ...
        yield producer.next.eq(1)
        clocks = 0
        for byte in data[1:]:
            clocks += 1
            yield producer.payload.eq(byte)
            yield

        # ... which should have taken len(data) - 1 cycles because we already sent the first byte.
        self.assertEqual(clocks, len(data) - 1)
        self.assertEqual((yield producer.payload), data[-1])

        # By now the consumer stream would also have picked up the first byte ...
        self.assertEqual((yield consumer.valid), 0)
        self.assertEqual((yield consumer.p.first), 1)
        self.assertEqual((yield consumer.p.data), data[0])

        # ... but the stream still won't advance ...
        yield
        self.assertEqual((yield consumer.valid), 0)
        self.assertEqual((yield consumer.p.first), 1)
        self.assertEqual((yield consumer.p.data), data[0])

        # ... until we finally mark the packet as complete and invalidate the producer stream.
        yield dut.interface.rx_complete.eq(1)
        yield producer.valid.eq(0)
        yield producer.next.eq(0)
        yield

        # After three clock cycles delay our stream goes finally valid ...
        yield
        yield
        yield
        self.assertEqual((yield consumer.valid), 1)

        # ... and we can now receive the packet.
        clocks = 0
        while (yield consumer.valid) and (yield consumer.p.last) == 0:
            clocks += 1
            received.append((yield consumer.p.data))
            yield

        self.assertEqual(received, data)
        self.assertEqual((yield consumer.p.last), 1)
        self.assertEqual((yield consumer.p.data), data[-1])
        self.assertEqual(clocks, len(data))

        # Finally, let's invalidate the consumer ...
        yield consumer.ready.eq(0)
        yield

        # ... and everything should be over.
        self.assertEqual((yield producer.valid), 0)
        self.assertEqual((yield producer.next), 0)
        self.assertEqual((yield consumer.ready), 0)
        self.assertEqual((yield consumer.valid), 0)
        self.assertEqual((yield consumer.p.first), 0)
        self.assertEqual((yield consumer.p.last), 0)
        self.assertEqual((yield consumer.p.data), 0)
