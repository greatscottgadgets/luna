#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Stream multiplexers/arbiters. """

from amaranth       import *
from .              import StreamInterface


class StreamMultiplexer(Elaboratable):
    """ Gateware that merges a collection of StreamInterfaces into a single interface.

    This variant performs no scheduling. Assumes that only one stream will be communicating at once.

    Attributes
    ----------
    output: StreamInterface(), output stream
        Our output interface; has all of the active busses merged together.
    """

    def __init__(self, stream_type=StreamInterface):
        """
        Parameters:
            stream_type   -- The type of stream we'll be multiplexing. Must be a subclass of StreamInterface.
        """

        # Collection that stores each of the interfaces added to this bus.
        self._inputs = []

        #
        # I/O port
        #
        self.output = stream_type()


    def add_input(self, input_interface):

        """ Adds a transmit interface to the multiplexer. """
        self._inputs.append(input_interface)


    def elaborate(self, platform):
        m = Module()

        #
        # Our basic functionality is simple: we'll build a priority encoder that
        # connects whichever interface has its .valid signal high.
        #

        conditional = m.If

        for interface in self._inputs:

            # If the given interface is asserted, drive our output with its signals.
            with conditional(interface.valid):
                m.d.comb += interface.attach(self.output)

            # After our first iteration, use Elif instead of If.
            conditional = m.Elif


        return m



class StreamArbiter(Elaboratable):
    """ Gateware that merges a collection of StreamInterfaces into a single interface.

    This variant uses a simple priority scheduler; and will use a standard valid/ready handshake
    to schedule a single stream to communicate at a time. Bursts of ``valid`` will never be interrupted,
    so streams will only be switched once the current transmitter drops ``valid`` low.


    Attributes
    ----------
    source: StreamInterface(), output stream
        Our output interface; has all of the active busses merged together.

    idle: Signal(), output
        Asserted when none of our streams is currently active.

    Parameters
    ----------
    stream_type: subclass of StreamInterface
        If provided, sets the type of stream we'll be multiplexing (and thus our output type).
    domain: str
        The name of the domain in which this arbiter should operate. Defaults to "sync".
    """

    def __init__(self, *, stream_type=StreamInterface, domain="sync"):
        self._domain = domain

        # Collection that stores each of the interfaces added to this bus.
        self._sinks = []

        #
        # I/O port
        #
        self.source = stream_type()
        self.idle   = Signal()


    def add_stream(self, stream):
        """ Adds a stream to our arbiter.

        Parameters
        ----------
        stream: StreamInterface subclass
            The stream to be added. Streams added first will have higher priority.
        """
        self._sinks.append(stream)


    def elaborate(self, platform):
        m = Module()
        active_stream = self.source

        # Keep track of which stream is currently active.
        stream_count        = len(self._sinks)
        active_stream_index = Signal(range(stream_count))

        #
        # Stream output multiplexer.
        #
        with m.Switch(active_stream_index):

            # Generate a switch case for each of our possible stream indexes..
            for index, stream in enumerate(self._sinks):
                with m.Case(index):

                    # ... and connect up the stream while in that case.
                    m.d.comb += active_stream.stream_eq(stream)


        #
        # Active stream selection.
        #

        # Only change which stream we're working with when the active stream stops transmitting.
        with m.If(~active_stream.valid):

            # Assume we're idle until proven otherwise.
            m.d.comb += self.idle.eq(1)

            # Check other streams to see if any are valid. We'll use a reversed list in order to maintain
            # our priority order; as the last assignment here "wins".
            for stream_index in reversed(range(stream_count)):

                # If another stream -is- valid, set it to be the active stream.
                with m.If(self._sinks[stream_index].valid):
                    m.d.comb += self.idle.eq(0)
                    m.d.sync += active_stream_index.eq(stream_index)


        # If we're operating in a domain other than sync, replace 'sync' with it.
        if self._domain != "sync":
            m =  DomainRenamer(self._domain)(m)

        return m
