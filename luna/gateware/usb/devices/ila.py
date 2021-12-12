#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Pre-made gateware that implements an ILA connection serial. """

from amaranth                          import Elaboratable, Module, Signal, Cat

from ...debug.ila                      import StreamILA, ILAFrontend
from ...stream                         import StreamInterface
from ..usb2.device                     import USBDevice
from ..usb2.request                    import USBRequestHandler, StallOnlyRequestHandler
from ..usb2.endpoints.stream           import USBMultibyteStreamInEndpoint

from usb_protocol.types                import USBRequestType
from usb_protocol.emitters             import DeviceDescriptorCollection
from usb_protocol.emitters.descriptors import cdc


class USBIntegratedLogicAnalyzer(Elaboratable):
    """ Pre-made gateware that presents a USB-connected ILA.

    Samples are presented over a USB endpoint.
    """

    BULK_ENDPOINT_NUMBER = 1

    def __init__(self, *args, bus=None, delayed_connect=False, max_packet_size=512, **kwargs):
        self._delayed_connect = delayed_connect
        self._max_packet_size = max_packet_size

        # Store our USB bus.
        self._bus = bus

        # Force the ILA's output into the USB domain.
        kwargs['o_domain'] = 'usb'

        # Create our core ILA, which we'll use later.
        self.ila = StreamILA(*args, **kwargs)

        #
        # I/O port
        #

        # Copy some core parameters from our inner ILA.
        self.signals          = self.ila.signals
        self.sample_width     = self.ila.sample_width
        self.sample_depth     = self.ila.sample_depth
        self.sample_rate      = self.ila.sample_rate
        self.sample_period    = self.ila.sample_period
        self.bits_per_sample  = self.ila.bits_per_sample
        self.bytes_per_sample = self.ila.bytes_per_sample

        # Expose our ILA's trigger and status ports directly.
        self.trigger  = self.ila.trigger
        self.sampling = self.ila.sampling
        self.complete = self.ila.complete



    def create_descriptors(self):
        """ Create the descriptors we want to use for our device. """

        descriptors = DeviceDescriptorCollection()

        #
        # We'll add the major components of the descriptors we we want.
        # The collection we build here will be necessary to create a standard endpoint.
        #

        # We'll need a device descriptor...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = 0x16d0
            d.idProduct          = 0x05a5

            d.iManufacturer      = "LUNA"
            d.iProduct           = "Integrated Logic Analyzer"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | self.BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self._max_packet_size


        return descriptors


    def elaborate(self, platform):
        m = Module()
        m.submodules.ila = self.ila

        # If we have a bus name rather than a bus object,
        # request the bus from our platform.
        if isinstance(self._bus, str):
            self._bus = platform.request(self._bus)

        # If we have no bus, grab the platform's default USB connection.
        if self._bus is None:
            self._bus = platform.request(platform.default_usb_connection)

        m.submodules.usb = usb = USBDevice(bus=self._bus)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)

        # Add a stream endpoint to our device.
        stream_ep = USBMultibyteStreamInEndpoint(
            endpoint_number=self.BULK_ENDPOINT_NUMBER,
            max_packet_size=self._max_packet_size,
            byte_width=self.ila.bytes_per_sample
        )
        usb.add_endpoint(stream_ep)

        # Handle our connection criteria: we'll either connect immediately,
        # or once sampling is done, depending on our _delayed_connect setting.
        connect = Signal()
        if self._delayed_connect:
            with m.If(self.ila.complete):
                m.d.usb += connect.eq(1)
        else:
            m.d.comb += connect.eq(1)

        # Connect up our I/O and our ILA streams.
        m.d.comb += [
            stream_ep.stream  .stream_eq(self.ila.stream),
            usb.connect       .eq(connect)
        ]

        return m



class USBIntegratedLogicAnalyzerFrontend(ILAFrontend):
    """ Frontend for USB-attached integrated logic analyzers.

    Parameters
    ------------
    delay: int
        The number of seconds to wait before trying to connect.
    ila: IntegratedLogicAnalyzer
        The ILA object to work with.
    """

    def __init__(self, *args, ila, delay=3, **kwargs):
        import usb
        import time

        # If we have a connection delay, wait that long.
        if delay:
            time.sleep(delay)

        # Create our USB connection the device
        self._device = usb.core.find(idVendor=0x16d0, idProduct=0x5a5)


        super().__init__(ila)


    def _split_samples(self, all_samples):
        """ Returns an iterator that iterates over each sample in the raw binary of samples. """
        from apollo_fpga.support.bits import bits

        sample_width_bytes = self.ila.bytes_per_sample

        # Iterate over each sample, and yield its value as a bits object.
        for i in range(0, len(all_samples), sample_width_bytes):
            raw_sample    = all_samples[i:i + sample_width_bytes]
            sample_length = len(Cat(self.ila.signals))

            yield bits.from_bytes(raw_sample, length=sample_length, byteorder='little')


    def _read_samples(self):
        """ Reads a set of ILA samples, and returns them. """

        sample_width_bytes = self.ila.bytes_per_sample
        total_to_read      = self.ila.sample_depth * sample_width_bytes

        # Fetch all of our samples from the given device.
        all_samples = self._device.read(0x81, total_to_read, timeout=0)
        return list(self._split_samples(all_samples))
