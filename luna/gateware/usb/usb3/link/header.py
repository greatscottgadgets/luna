#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Header Packet data interfacing definitions."""

import operator
import functools

from enum import IntEnum

from amaranth           import *
from amaranth.hdl.rec   import Layout

from ....stream.arbiter import StreamArbiter


class HeaderPacket(Record):
    """ Container that represents a Header Packet. """

    # Create overrideable constants that allow us to specialize
    # the data words of our headers in subclasses.
    DW0_LAYOUT = [('dw0', 32)]
    DW1_LAYOUT = [('dw1', 32)]
    DW2_LAYOUT = [('dw2', 32)]

    LINK_LAYER_FIELDS = [
        ('crc16',           16),
        ('sequence_number',  3),
        ('dw3_reserved',     3),
        ('hub_depth',        3),
        ('delayed',          1),
        ('deferred',         1),
        ('crc5',             5),
    ]

    def get_type(self):
        """ Returns the selection of bits in DW0 that encode the packet type. """
        return self.dw0[0:5]


    @classmethod
    def get_layout(cls):
        """ Computes the layout for the HeaderPacket (sub)class. """
        return [
            *cls.DW0_LAYOUT,
            *cls.DW1_LAYOUT,
            *cls.DW2_LAYOUT,
            *cls.LINK_LAYER_FIELDS
        ]


    def __init__(self):
        super().__init__(self.get_layout(), name=self.__class__.__name__)



class HeaderQueue(Record):
    """ Record representing a header, and stream-link control signals.

    Attributes
    ----------
    valid: Signal(), producer to consumer
        Indicates that the data in :attr:``header`` is valid and ready to be consumed.
    header: HeaderPacket(), producer to consumer
        Contains a full set of header packet data.
    ready: Signal(), consumer to producer
        Strobed by the consumer to indicate that it has accepted the given header.
    """

    def __init__(self, *, header_type=HeaderPacket):
        super().__init__([
            ('valid', 1),
            ('header', header_type.get_layout()),
            ('ready', 1),
        ], name="HeaderQueue")


    def get_type(self):
        """ Returns the selection of bits in the current header's that encode the packet type. """
        return self.header.dw0[0:5]


    def header_eq(self, other):
        """ Connects a producer (self) up to a consumer. """
        return [
            self.valid   .eq(other.valid),
            self.header  .eq(other.header),
            other.ready  .eq(self.ready)
        ]


    def stream_eq(self, other):
        """ Alias for ``header_eq`` that ensures we share a stream interface. """
        return self.header_eq(other)



class HeaderQueueArbiter(StreamArbiter):
    """ Gateware that accepts a collection of header queues, and merges them into a single queue.

    Add produces using ``add_producer``.

    Attributes
    ----------
    source: HeaderQueue(), output queue
        A single header queue that carries data from all producer queues.
    """

    def __init__(self):
        super().__init__(stream_type=HeaderQueue, domain="ss")


    def add_producer(self, interface: HeaderQueue):
        """ Adds a HeaderQueue interface that will add packets into this mux. """
        self.add_stream(interface)



class HeaderQueueDemultiplexer(Elaboratable):
    """ Gateware that accepts a single Header Queue, and routes it to multiple modules.

    Assumes that each type of header is handled by a separate module, and thus no two inputs
    will assert :attr:``ready`` at the same time.

    Add consumers using ``add_consumer``.

    Attributes
    ----------
    sink: HeaderQueue(), input queue
        The single header queue to be distributed to all of our consumers.
    """

    def __init__(self):
        self._consumers = []

        #
        # I/O port
        #
        self.sink = HeaderQueue()


    def add_consumer(self, interface: HeaderQueue):
        """ Adds a HeaderQueue interface that will consume packets from this mux. """
        self._consumers.append(interface)


    def elaborate(self, platform):
        m = Module()

        # Share the ``valid`` signal and header itself with every consumer.
        for consumer in self._consumers:
            m.d.comb += [
                consumer.valid   .eq(self.sink.valid),
                consumer.header  .eq(self.sink.header),
            ]

        # OR together all of the ``ready`` signals to produce our multiplex'd ready.
        sink_ready = functools.reduce(operator.__or__, (c.ready for c in self._consumers))
        m.d.comb += self.sink.ready.eq(sink_ready)


        return m
