#
# This file is part of LUNA.
#
""" Stream multiplexers/arbiters. """

from nmigen         import Elaboratable, Signal, Module
from .              import StreamInterface

class StreamMultiplexer(Elaboratable):
    """ Gateware that merges a collection of StreamInterfaces into a single interface.

    Assumes that only one stream will be communicating at once.

    I/O port:
        O*: output -- Our output interface; has all of the active busses merged together.
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
