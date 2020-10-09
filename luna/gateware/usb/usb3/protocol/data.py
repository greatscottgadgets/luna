#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Data Packet handling gateware. """

from nmigen import *
from usb_protocol.types.superspeed import HeaderPacketType

from ..link.header import HeaderQueue
from ..link.data   import DataHeaderPacket
from ...stream     import SuperSpeedStreamInterface
from ...request    import SetupPacket


class DataHeaderReceiver(Elaboratable):
    """ Gateware that handles received Data Header packets.

    Attributes
    -----------
    header_sink: HeaderQueue(), input stream
        Stream that brings up header packets for handling.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.header_sink   = HeaderQueue()


    def elaborate(self, platform):
        m = Module()

        # We handle Data Packets specially, passing their header data in conjunction with
        # the packets themselves; but the header packets are still handled like other header
        # packets, and must be explicitly consumed by the protocol layer.
        #
        # We'll consume all of them here, since we don't have any direct use for their data.
        new_packet = self.header_sink.valid
        is_for_us  = self.header_sink.get_type() == HeaderPacketType.DATA
        with m.If(new_packet & is_for_us):
            m.d.comb += self.header_sink.ready.eq(1)

        return m



class SuperSpeedSetupDecoder(Elaboratable):
    """ Gateware that decodes any received Setup packets.

    Attributes
    -----------
    sink: SuperSpeedStreamInterface(), input stream [read-only]
        Packet interface that carres in new data packets. Results should be considered questionable
        until :attr:``packet_good`` or :attr:``packet_bad`` are strobed.

    rx_good: Signal(), input
        Strobe; indicates that the packet received passed validations and can be considered good.
    rx_bad: Signal(), input
        Strobe; indicates that the packet failed CRC checks, or did not end properly.

    header_in: DataHeaderPacket(), input
        Header associated with the active packet.

    packet: SetupPacket(), output
        The parsed contents of our setup packet.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.sink       = SuperSpeedStreamInterface()

        self.rx_good    = Signal()
        self.rx_bad     = Signal()

        self.header_in  = DataHeaderPacket()

        self.packet     = SetupPacket()


    def elaborate(self, platform):
        m = Module()

        # Capture our packet locally, until we have an entire valid packet.
        packet = SetupPacket()

        # Keep our "received" flag low unless explicitly driven.
        m.d.ss += self.packet.received.eq(0)

        led = platform.request("led", 2)

        with m.FSM(domain="ss"):

            # WAIT_FOR_FIRST -- we're waiting for the first word of a setup packet;
            # which we'll handle on receipt.
            with m.State("WAIT_FOR_FIRST"):
                packet_starting = self.sink.valid.all() & self.sink.first
                packet_is_setup = (self.header_in.setup)

                # Once we see the start of a new setup packet, parse it, and move to the second word.
                with m.If(packet_starting & packet_is_setup):
                    m.d.ss += packet.word_select(0, 32).eq(self.sink.data)
                    m.next = "PARSE_SECOND"

            # PARSE_SECOND -- handle the second and last packet, which contains the remainder of
            # our setup data.
            with m.State("PARSE_SECOND"):
                m.d.ss += led.eq(1)

                with m.If(self.sink.valid.all()):

                    # This should be our last word; parse it.
                    with m.If(self.sink.last):
                        m.d.ss += packet.word_select(1, 32).eq(self.sink.data)
                        m.next = "WAIT_FOR_VALID"

                    # If this wasn't our last word, something's gone very wrong.
                    # We'll ignore this packet.
                    with m.Else():
                        m.next = "WAIT_FOR_FIRST"

                # If we see :attr:``rx_bad``, this means our packet aborted early,
                # and thus isn't a valid setup packet. Ignore it, and go back to waiting
                # for our first packet.
                with m.If(self.rx_bad):
                        m.next = "WAIT_FOR_FIRST"

            # WAIT_FOR_VALID -- we've now received all of our data; and we're just waiting
            # for an indication of  whether the data is good or bad.
            with m.State("WAIT_FOR_VALID"):

                # If we see :attr:``packet_good``, this means we have a valid setup packet!
                # We'll output it, and indicate that we've received a new packet.
                with m.If(self.rx_good):
                    m.d.ss += [
                        # Output our stored packet...
                        self.packet           .eq(packet),

                        # ... but strobe its received flag for a cycle.
                        self.packet.received  .eq(1)
                    ]
                    m.next = "WAIT_FOR_FIRST"

                # If we see :attr:``packet_bad``, this means our packet failed CRC checks.
                # We can't do anything with it; so we'll just ignore it.
                with m.If(self.rx_bad):
                    m.next = "WAIT_FOR_FIRST"

        return m
