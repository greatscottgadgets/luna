#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Data Packet Payload (DPP) management gateware. """

import unittest

from nmigen import *

from usb_protocol.types import USBDirection
from usb_protocol.types.superspeed import HeaderPacketType

from .crc              import HeaderPacketCRC, DataPacketPayloadCRC, compute_usb_crc5
from .header           import HeaderPacket, HeaderQueue

from ..physical.coding import SHP, SDP, EPF, stream_matches_symbols
from ...stream         import USBRawSuperSpeedStream, SuperSpeedStreamInterface
from ....test.utils    import LunaSSGatewareTestCase, ss_domain_test_case


class DataHeaderPacket(HeaderPacket):
    DW0_LAYOUT = [
        ('type',                5),
        ('route_string',       20),
        ('device_address',      7),
    ]
    DW1_LAYOUT = [
        ('data_sequence',       5),
        ('reserved_0',          1),
        ('end_of_burst',        1),
        ('direction',           1),
        ('endpoint_number',     4),
        ('reserved_1',          3),
        ('setup',               1),
        ('data_length',        16),
    ]
    DW2_LAYOUT = [
        ('stream_id',          16),
        ('reserved_2',         11),
        ('packet_pending',      1),
        ('reserved_3',          4),
    ]



class DataPacketReceiver(Elaboratable):
    """ Class that monitors the USB bus for data packets, and receives them.

    This class has logic redundant with our Header Packet Receiver, to simplify data packet
    reception. Accordingly, the header section of the data packet will be parsed here as well
    as in the Header Packet receiver. This simplifies our structure at the expense of an additional
    CRC-5 and CRC-16 unit.

    This class performs the validations required at the link layer of the USB specification;
    which include checking the CRC-5 and CRC-16 embedded within the header, and CRC-32 of the
    data packet payload.

    Header sequence number is not checked, here, as a sequence error will force recovery in the
    Header Packet Receiver.


    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input (monitor only)
        Stream that the USB data to be monitored.

    header: HeaderPacket(), output
        The header packet accompanying the current data packet. Valid once a packet begins
        to be received.
    new_header: Signal(), output
        Strobe; indicates that :attr:``header`` has been updated.
    source: StreamInterface(), output stream
        A stream carrying the data received. Note that the data is not fully validated until
        the packet has been fully received; so this cannot be assumed

    packet_good: Signal(), output
        Strobe; indicates that the packet received passed validations and can be considered good.
    packet_bad: Signal(), output
        Strobe; indicates that the packet failed CRC checks, or did not end properly.
    """

    MAX_PACKET_SIZE = 1024

    def __init__(self):

        #
        # I/O port
        #
        self.sink              = USBRawSuperSpeedStream()

        # Header and data output.
        self.header            = DataHeaderPacket()
        self.new_header        = Signal()
        self.source            = SuperSpeedStreamInterface()

        # State indications.
        self.packet_good       = Signal()
        self.packet_bad        = Signal()



    def elaborate(self, platform):
        m = Module()

        sink   = self.sink
        source = self.source

        # Store our header packet in progress; which we'll output only once it's been validated.
        # We'll store it our generic way; and then refine it as our data becomes valid.
        header = HeaderPacket()

        # Cache our expected CRC5, so we can pipeline generation and comparison.
        expected_crc5 = Signal(5)

        # Store how much data is remaining in the given packet.
        data_bytes_remaining = Signal(range(self.MAX_PACKET_SIZE + 1))

        #
        # CRC Generators
        #
        m.submodules.crc16 = crc16 = HeaderPacketCRC()
        m.d.comb += crc16.data_input.eq(sink.data),

        m.submodules.crc32 = crc32 = DataPacketPayloadCRC()
        m.d.comb += crc32.data_input.eq(sink.data),


        #
        # Receiver Sequencing
        #
        with m.FSM(domain="ss"):

            # WAIT_FOR_HPSTART -- we're currently waiting for HPSTART framing, which indicates
            # that the following 16 symbols (4 words) will be a header packet.
            with m.State("WAIT_FOR_HPSTART"):

                # Don't start our CRCs until we're past our HPSTART header.
                m.d.comb += [
                    crc16.clear.eq(1),
                    crc32.clear.eq(1),
                ]

                is_hpstart = stream_matches_symbols(sink, SHP, SHP, SHP, EPF)
                with m.If(is_hpstart):
                    m.next = "RECEIVE_DW0"

            # RECEIVE_DWn -- the first three words of our header packet are data words meant form
            # the protocol layer; we'll receive them so we can pass them on to the protocol layer.
            for n in range(3):
                with m.State(f"RECEIVE_DW{n}"):

                    with m.If(sink.valid):
                        m.d.comb += crc16.advance_crc.eq(1)
                        m.d.ss += header[f'dw{n}'].eq(sink.data)
                        m.next = f"RECEIVE_DW{n+1}"

                        # Extra check for our first packet; we'll make sure this of -data- type;
                        # and bail out, otherwise.
                        if n == 0:
                            with m.If(sink.data[0:5] != HeaderPacketType.DATA):
                                m.next = "WAIT_FOR_HPSTART"


            # RECEIVE_DW3 -- we'll receive and parse our final data word, which contains the fields
            # relevant to the link layer.
            with m.State("RECEIVE_DW3"):

                with m.If(sink.valid):
                    m.d.ss += [
                        # Collect the fields from the DW...
                        header.crc16            .eq(sink.data[ 0:16]),
                        header.sequence_number  .eq(sink.data[16:19]),
                        header.dw3_reserved     .eq(sink.data[19:22]),
                        header.hub_depth        .eq(sink.data[22:25]),
                        header.deferred         .eq(sink.data[25]),
                        header.delayed          .eq(sink.data[26]),
                        header.crc5             .eq(sink.data[27:32]),

                        # ... and pipeline a CRC of the to the link control word.
                        expected_crc5           .eq(compute_usb_crc5(sink.data[16:27]))
                    ]

                    m.next = "CHECK_HEADER"

            # CHECK_PACKET -- we've now received our full packet; we'll check it for validity.
            with m.State("CHECK_HEADER"):
                crc5_failed  = (expected_crc5 != header.crc5)
                crc16_failed = (crc16.crc     != header.crc16)

                # If either of our CRCs fail, this isn't going to be followed by a DPP we care about.
                with m.If(crc5_failed | crc16_failed):
                    m.next = "WAIT_FOR_HPSTART"

                # Otherwise, if we have a data packet header, move to capturing our data.
                with m.Elif(stream_matches_symbols(sink, SDP, SDP, SDP, EPF)):
                    m.d.ss += [
                        # Update the header associated with the active packet.
                        self.header           .eq(header),
                        self.new_header       .eq(1),

                        # Read the data length from our header, in preparation to receive it.
                        data_bytes_remaining  .eq(header.dw1[16:]),

                        # Mark the next packet as the first packet in our stream.
                        source.first          .eq(1)
                    ]

                    # Move to receiving data.
                    m.next = "RECEIVE_PAYLOAD"

                # If our data is valid and we're -not- a start of DPP, this isn't for us.
                # Go back to watching for data.
                with m.Elif(sink.valid):
                    m.next = "WAIT_FOR_HPSTART"

            # RECEIVE_PAYLOAD -- receive the core data payload
            with m.State("RECEIVE_PAYLOAD"):
                m.d.comb += [
                    # Pass through most our data directly.
                    source.data         .eq(sink.data),

                    # Manage each of our byte-valid bits directly.
                    source.valid[0]     .eq((data_bytes_remaining > 0) & sink.valid),
                    source.valid[1]     .eq((data_bytes_remaining > 1) & sink.valid),
                    source.valid[2]     .eq((data_bytes_remaining > 2) & sink.valid),
                    source.valid[3]     .eq((data_bytes_remaining > 3) & sink.valid),

                    # Advance our CRC according to how many bytes are currently valid.
                    crc32.advance_word  .eq(source.valid == 0b1111),
                    crc32.advance_3B    .eq(source.valid == 0b0111),
                    crc32.advance_2B    .eq(source.valid == 0b0011),
                    crc32.advance_1B    .eq(source.valid == 0b0001),

                    # Mark this packet as the last one if we've a word or less remaining.
                    source.last         .eq(data_bytes_remaining <= 4)
                ]

                with m.If(sink.valid):
                    # Once we've moved on, this is no longer our first word.
                    m.d.ss += source.first.eq(0)

                    # If we see unexpected control codes in our data packet, bail out.
                    with m.If(sink.ctrl & source.valid):
                        m.d.comb += self.packet_bad.eq(1)
                        m.next = "WAIT_FOR_HPSTART"

                    # If we have another word to receive after this, decrement our count,
                    # and continue.
                    with m.If(data_bytes_remaining > 4):
                        m.d.ss += data_bytes_remaining.eq(data_bytes_remaining - 4)

                    with m.Else():
                        m.next = "CHECK_CRC32"


            # CHECK_CRC32 -- we've received the end of our packet; and we're ready to decide if the
            # packet is good or not. We'll check its CRC, and strobe either packet_good or packet_bad.
            with m.State("CHECK_CRC32"):

                # FIXME: deal with unaligned CRCs?
                crc_valid = (sink.data == crc32.crc)
                with m.If(crc_valid):
                    m.d.comb += self.packet_good.eq(1)
                with m.Else():
                    m.d.comb += self.packet_bad.eq(1)

                m.next = "WAIT_FOR_HPSTART"


        return m



class DataPacketReceiverTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = DataPacketReceiver

    def initialize_signals(self):
        yield self.dut.sink.valid.eq(1)

    def provide_data(self, *tuples):
        """ Provides the receiver with a sequence of (data, ctrl) values. """

        # Provide each word of our data to our receiver...
        for data, ctrl in tuples:
            yield self.dut.sink.data.eq(data)
            yield self.dut.sink.ctrl.eq(ctrl)
            yield


    @ss_domain_test_case
    def test_aligned_packet_receive(self):

        # Provide a packet pair to the device.
        # (This data is from an actual recorded data packet.)
        yield from self.provide_data(
            # Header packet.
            # data       ctrl
            (0xF7FBFBFB, 0b1111),
            (0x00000008, 0b0000),
            (0x00088000, 0b0000),
            (0x08000000, 0b0000),
            (0xA8023E0F, 0b0000),

            # Payload packet.
            (0xF75C5C5C, 0b1111),
            (0x001E0500, 0b0000),
            (0x00000000, 0b0000),
            (0x0EC69325, 0b0000),
        )

        self.assertEqual((yield self.dut.packet_good), 1)



class DataPacketTransmitter(Elaboratable):
    """ Gateware that generates a Data Packet Header, and orchestrates sending it and a payload.

    The actual sending is handled by our transmitter gateware.

    Attributes
    ----------
    data_sink: SuperSpeedStreamInterface(), input stream
        The data stream to be send as a data packet. The length of this stream should match thee
        length parameter.

    sequence_number: Signal(5), input
        The sequence number associated with the relevant data packet. Latched in once :attr:``data_sink`` goes valid.
    endpoint_number: Signal(4), input
        The endpoint number associated with the relevant data stream. Latched in once :attr:``data_sink`` goes valid.
    data_length: Signal(range(1024 + 1))
        The length of the data packet to be sent; in bytes. Latched in once :attr:``data_sink`` goes valid.
    """

    MAX_PACKET_SIZE = 1024

    def __init__(self):

        #
        # I/O port
        #

        # Input stream.
        self.data_sink       = SuperSpeedStreamInterface()

        # Data parameters.
        self.sequence_number = Signal(5)
        self.endpoint_number = Signal(4)
        self.data_length     = Signal(range(self.MAX_PACKET_SIZE + 1))
        self.address         = Signal(7)

        # Output streams.
        self.header_source   = HeaderQueue()
        self.data_source     = SuperSpeedStreamInterface()


    def elaborate(self, platform):
        m = Module()

        # Shortcuts.
        header_source = self.header_source
        data_sink     = self.data_sink
        data_source   = self.data_source

        # Latched resources.
        sequence_number = Signal.like(self.sequence_number)
        endpoint_number = Signal.like(self.endpoint_number)
        data_length     = Signal.like(self.data_length)


        # For now, we'll pass our data stream through unmodified.
        #
        # We'll keep this architecture; as later code is likely to want to more actively
        # control when data is passed through to the transmitter.
        m.d.comb += data_source.stream_eq(data_sink)


        with m.FSM(domain="ss"):

            # WAIT_FOR_DATA -- we're idly waiting for our input data stream to become valid.
            with m.State("WAIT_FOR_DATA"):

                # Constantly latch in our data parameters until we get a new data packet.
                m.d.ss += [
                    sequence_number  .eq(self.sequence_number),
                    endpoint_number  .eq(self.endpoint_number),
                    data_length      .eq(self.data_length)
                ]

                # Once our data goes valid, begin sending our data.
                with m.If(data_sink.valid.any()):
                    m.next = "SEND_HEADER"


            # SEND_HEADER -- we're sending the header associated with our data packet.
            with m.State("SEND_HEADER"):
                header = DataHeaderPacket()
                m.d.comb += [
                    header_source.header    .eq(header),
                    header_source.valid     .eq(1),

                    # We're sending a data packet from up to the host.
                    header.type             .eq(HeaderPacketType.DATA),
                    header.direction        .eq(USBDirection.IN),
                    header.device_address   .eq(self.address),

                    # Fill in our input parameters...
                    header.data_sequence    .eq(sequence_number),
                    header.data_length      .eq(data_length),
                    header.endpoint_number  .eq(endpoint_number),
                ]

                # Once our header is accepted, move on to passing through our payload.
                with m.If(header_source.ready):
                    m.next = "SEND_PAYLOAD"


            # SEND_PAYLOAD -- we're now passing our payload data to our transmitter; which will
            # drive ready when it's time to accept data.
            with m.State("SEND_PAYLOAD"):

                # Once our packet is complete, we'll go back to idle.
                with m.If(~data_sink.valid.any()):
                    m.next = "WAIT_FOR_DATA"

        return m


if __name__ == "__main__":
    unittest.main()
