#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Utilities for building USB3 descriptors into gateware. """

from amaranth                          import *
from usb_protocol.emitters.descriptors import DeviceDescriptorCollection

from ...stream                         import SuperSpeedStreamInterface
from ....stream.generator              import ConstantStreamGenerator


class GetDescriptorHandler(Elaboratable):
    """ Gateware that handles responding to GetDescriptor requests.

    Currently does not support descriptors in multiple languages.

    Attributes
    ----------
    value: Signal(16), input
        The value field associated with the Get Descriptor request. Contains the descriptor type and index.
    length: Signal(16), input
        The length field associated with the Get Descriptor request.
        Determines the maximum amount allowed in a response.

    start: Signal(), input
        Strobe that indicates when a descriptor should be transmitted.

    tx: stream_type(), output stream
        Stream that carries our output descriptor data.
    tx_length: Signal(16), output
        The actual length of the descriptor to be sent. At SuperSpeed, used for header generation.

    stall: Signal(), output
        Strobe; pulsed if a STALL handshake should be generated, instead of a response.

    Parameters
    ----------
    domain: string
        The clock domain this generator should belong to. Defaults to ''.
    stream_type: StreamInterface, or subclass
        The type of stream we'll be multiplexing.
    """

    def __init__(self, descriptor_collection: DeviceDescriptorCollection, *,
        usb_domain="ss", stream_type=SuperSpeedStreamInterface):
        """
        Parameters
        ----------
        descriptor_collection: DeviceDescriptorCollection
            The DeviceDescriptorCollection containing the descriptors to use for this device.
        usb_domain: string
            The name of the domain to use for USB data exchange.
        stream_type: StreamInterface subclass
            The type of the stream to be used to carry descriptor data.
        """
        self._domain      = usb_domain
        self._descriptors = descriptor_collection
        self._stream_type = stream_type

        #
        # I/O port
        #
        self.value     = Signal(16)
        self.length    = Signal(16)

        self.start     = Signal()

        self.tx        = stream_type()
        self.tx_length = Signal(16)
        self.stall     = Signal()


    def elaborate(self, platform):
        m = Module()

        # Collection that will store each of our descriptor-generation submodules.
        descriptor_generators = {}

        #
        # Create our constant-stream generators for each of our descriptors.
        #
        for type_number, index, raw_descriptor in self._descriptors:

            # Create the generator...
            generator = ConstantStreamGenerator(raw_descriptor,
                domain=self._domain, stream_type=self._stream_type, max_length_width=16)
            descriptor_generators[(type_number, index)] = generator

            # ... and attach it to this module.
            m.submodules += generator


        #
        # Connect up each of our generators.
        #

        with m.Switch(self.value):

            # Generate a conditional interconnect for each of our items.
            for (type_number, index), generator in descriptor_generators.items():

                # If the value matches the given type number...
                with m.Case(type_number << 8 | index):

                    # ... connect the relevant generator to our output.
                    m.d.comb += [
                        generator.start       .eq(self.start),
                        generator.max_length  .eq(self.length),
                    ]

                    # Buffer the output stream to improve timings.
                    with m.If(~self.tx.valid.any() | self.tx.ready):
                        m.d.sync += [
                            self.tx               .stream_eq(generator.stream, omit={'ready'}),
                            self.tx_length        .eq(generator.output_length)
                        ]
                        m.d.comb += [
                            generator.stream.ready.eq(1),
                        ]

            # If none of our descriptors match, stall any request that comes in.
            with m.Case():
                m.d.comb += self.stall.eq(self.start)

        # Convert our sync domain to the domain requested by the user, if necessary.
        if self._domain != "sync":
            m = DomainRenamer({"sync": self._domain})(m)

        return m
