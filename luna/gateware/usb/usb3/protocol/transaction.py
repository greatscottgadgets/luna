#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Protocol-level Transaction Packet (flow control header) generation. """

from nmigen import *
from nmigen.hdl.rec import DIR_FANOUT, DIR_FANIN

from usb_protocol.types import USBDirection
from usb_protocol.types.superspeed import HeaderPacketType, TransactionPacketSubtype

from ..link.header import HeaderQueue, HeaderPacket

#
# Interfaces.
#

class HandshakeGeneratorInterface(Record):
    """ Interface used by an endpoint to generate transaction packets.

    Attributes
    -----------
    endpoint_number: Signal(7), input to handshake generator
        The endpoint number associated with the transaction packet to be generated.
    retry_required: Signal(), input to handshake generator
        If set, an ACK will be interpreted as a request to re-send the relevant packet.
    next_sequence: Signal(5), input to handshake generator
        Reports the next expected data packet sequence number to the host.

    send_ack: Signal(), input to handshake generator
        Strobe; requests generation of an ACK packet.

    ready: Signal(), output from handshake generator
        Asserted when the handshake generator is ready to accept new signals.
    done: Signal(), output from handshake geneartor.
        Strobe; pulsed when a requested send is complete.
    """

    def __init__(self):
        super().__init__([

            # Parameters.
            ('endpoint_number', 7, DIR_FANIN),
            ('retry_required',  1, DIR_FANIN),
            ('next_sequence',   5, DIR_FANIN),

            # Commands.
            ('send_ack',        1, DIR_FANIN),

            # Status.
            ('ready',           1, DIR_FANOUT),
            ('done',            1, DIR_FANOUT),

        ])


class HandshakeReceiverInterface(Record):
    """ Interface used by an endpoint to generate transaction packets.

    Attributes
    -----------
    endpoint_number: Signal(7), input to handshake generator
        The endpoint number associated with the transaction packet to be generated.
    retry_required: Signal(), input to handshake generator
        If set, an ACK will be interpreted as a request to re-send the relevant packet.
    next_sequence: Signal(5), input to handshake generator
        Reports the next expected data packet sequence number to the host.

    send_ack: Signal(), input to handshake generator
        Strobe; requests generation of an ACK packet.

    ready: Signal(), output from handshake generator
        Asserted when the handshake generator is ready to accept new signals.
    done: Signal(), output from handshake geneartor.
        Strobe; pulsed when a requested send is complete.
    """

    def __init__(self):
        super().__init__([

            # Parameters.
            ('endpoint_number', 7, DIR_FANOUT),
            ('retry_required',  1, DIR_FANOUT),
            ('next_sequence',   5, DIR_FANOUT),

            # Commands.
            ('status_received', 1, DIR_FANOUT),
        ])


#
# Transaction header packets.
#

class TransactionHeaderPacket(HeaderPacket):
    DW0_LAYOUT = [
        ('type',                5),
        ('route_string',       20),
        ('device_address',      7),
    ]


class ACKHeaderPacket(TransactionHeaderPacket):
    DW1_LAYOUT = [
        ('subtype',             4),
        ('reserved_0',          2),
        ('retry',               1),
        ('direction',           1),
        ('endpoint_number',     4),
        ('transfer_type',       3),  # Not used in Gen1.
        ('host_error',          1),
        ('number_of_packets',   5),
        ('data_sequence',       5),
        ('reserved_1',          5),
        ('tp_follows',          1),  # Not used in Gen1.
    ]
    DW2_LAYOUT = [
        ('stream_id',          16),
        ('reserved_2',         11),
        ('packets_pending',     1), # Host only.
        ('reserved_3',          4),
    ]


class StatusHeaderPacket(TransactionHeaderPacket):
    DW1_LAYOUT = [
        ('subtype',             4),
        ('reserved_0',          3),
        ('direction',           1),
        ('endpoint_number',     4),
        ('reserved_1',         20),
    ]



class TransactionPacketGenerator(Elaboratable):
    """ Module responsible for generating Token Packets, for flow control.

    Attributes
    ----------
    header_source: HeaderQueue(), output stream
        The stream that carries any generated header packet requests.
    interface: HandshakeGeneratorInterface(), to/from endpoint
        The control interface for our packet; meant to be carried to various endpoints.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.header_source   = HeaderQueue()
        self.interface       = HandshakeGeneratorInterface()



    def elaborate(self, platform):
        m = Module()

        header_source = self.header_source
        interface     = self.interface

        # Latched versions of each of our arguments.
        endpoint_number = Signal.like(interface.endpoint_number)
        data_error      = Signal.like(interface.retry_required)
        next_sequence   = Signal.like(interface.next_sequence)


        def send_packet(response_type, **fields):
            """ Helper that allows us to easily define a packet-send state."""

            # Create a response packet, and mark ourselves as sending it.
            response = response_type()
            m.d.comb += [
                header_source.valid    .eq(1),
                header_source.header   .eq(response),

                response.type          .eq(HeaderPacketType.TRANSACTION)
            ]

            # Next, fill in each of the fields:
            for field, value in fields.items():
                m.d.comb += response[field].eq(value)


        with m.FSM(domain="ss"):

            # DISPATCH_REQUESTS -- we're actively waiting for any generation requests that come in;
            # and preparing to handle them.
            with m.State("DISPATCH_REQUESTS"):
                m.d.comb += interface.ready.eq(1)

                # In this state, we'll constantly latch in our parameters.
                m.d.ss += [
                    endpoint_number  .eq(interface.endpoint_number),
                    data_error       .eq(interface.retry_required),
                    next_sequence    .eq(interface.next_sequence)
                ]

                with m.If(interface.send_ack):
                    m.next = "SEND_ACK"

            # SEND_ACK -- actively send an ACK packet to our link partner; and wait for that to complete.
            with m.State("SEND_ACK"):
                send_packet(ACKHeaderPacket,
                    subtype           = TransactionPacketSubtype.ACK,
                    direction         = USBDirection.OUT,
                    endpoint_number   = endpoint_number,
                    retry             = data_error,
                    data_sequence     = next_sequence,

                    # TODO: eventually support bursting?
                    number_of_packets = 1,
                )

                with m.If(header_source.ready):
                    m.d.comb += interface.done.eq(1)
                    m.next = "DISPATCH_REQUESTS"

        return m



class TransactionPacketReceiver(Elaboratable):
    """ Module responsible for receiving Transaction Packets from the host.

    Attributes
    ----------
    header_sink: HeaderQueue(), input stream
        The stream that carries received header packets up from the host.
    interface: HandshakeReceiverInterface(), output to endpoint
        Interface that detects transaction packets and reports them to the endpoint.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.header_sink     = HeaderQueue()
        self.interface       = HandshakeReceiverInterface()


    def elaborate(self, platform):
        m = Module()

        header_sink = self.header_sink
        interface   = self.interface

        # Figure out the vitals for the relevant packet.
        new_packet = header_sink.valid
        is_for_us  = header_sink.get_type() == HeaderPacketType.TRANSACTION

        # Handle any transaction packets.
        with m.If(new_packet & is_for_us):

            # We'll handle the relevant header this cycle; so we can take them off
            # the link layer's hands.
            m.d.comb += header_sink.ready.eq(1)

            # Handle the packet according to its subtype.
            with m.Switch(header_sink.header.dw1[0:4]):

                #
                # STATUS packets -- packets requesting a status stage handshake.
                #
                with m.Case(TransactionPacketSubtype.STATUS):

                    # Handle our packet as a status packet...
                    status_packet = StatusHeaderPacket()
                    m.d.comb += status_packet.eq(header_sink.header)

                    m.d.comb += [
                        # ... fill the fields out in our interface...
                        interface.endpoint_number  .eq(status_packet.endpoint_number),

                        # ... and report the event.
                        interface.status_received  .eq(1)
                    ]




        return m
