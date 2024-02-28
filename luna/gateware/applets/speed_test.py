from amaranth                import *
from usb_protocol.emitters   import DeviceDescriptorCollection, SuperSpeedDeviceDescriptorCollection

from luna.usb2               import USBDevice, USBStreamInEndpoint, USBStreamOutEndpoint
from luna.usb3               import USBSuperSpeedDevice, SuperSpeedStreamInEndpoint

from luna.gateware.platform  import NullPin

VENDOR_ID  = 0x16d0
PRODUCT_ID = 0x0f3b

BULK_ENDPOINT_NUMBER = 1


class USBSpeedTestDevice(Elaboratable):
    """ Simple device that exchanges data with the host as fast as the hardware can. """

    def __init__(self, generate_clocks=True, fs_only=False, phy=None,
            vid=VENDOR_ID, pid=PRODUCT_ID):
        self.generate_clocks = generate_clocks
        self.fs_only = fs_only
        self.phy = phy
        self.vid = vid
        self.pid = pid
        self.max_bulk_packet_size = 64 if fs_only else 512

    def create_descriptors(self):
        """ Create the descriptors we want to use for our device. """

        descriptors = DeviceDescriptorCollection()

        #
        # We'll add the major components of the descriptors we we want.
        # The collection we build here will be necessary to create a standard endpoint.
        #

        # We'll need a device descriptor...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = self.vid
            d.idProduct          = self.pid

            d.iManufacturer      = "LUNA"
            d.iProduct           = "speed test"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                # Bulk IN to host (tx, from our side)
                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.max_bulk_packet_size

                # Bulk OUT to host (rx, from our side)
                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.max_bulk_packet_size


        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        if self.generate_clocks:
            m.submodules.clocks = platform.clock_domain_generator()

        # Request default PHY unless another was specified.
        if self.phy is None:
            ulpi = platform.request(platform.default_usb_connection)
        else:
            ulpi = self.phy

        # Create our USB device interface...
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        assert not usb.always_fs or self.fs_only, \
               "fs_only must be set for devices with a full speed only PHY"

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)


        # Add a stream endpoint to our device for Bulk IN transfers.
        stream_in_ep = USBStreamInEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=self.max_bulk_packet_size
        )
        usb.add_endpoint(stream_in_ep)

        # Create a simple data source that increments whenever the
        # endpoint is accepting data.
        counter = Signal(8)
        with m.If(stream_in_ep.stream.ready):
            m.d.sync += counter.eq(counter + 1)

        # Send our IN data stream, as fast as we can.
        m.d.comb += [
            stream_in_ep.stream.valid    .eq(1),
            stream_in_ep.stream.payload  .eq(counter)
        ]


        # Add a stream endpoint to our device for Bulk OUT transfers.
        stream_out_ep = USBStreamOutEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=self.max_bulk_packet_size
        )
        usb.add_endpoint(stream_out_ep)

        # Always accept data as it comes in.
        m.d.comb += stream_out_ep.stream.ready.eq(1)

        # Receive our OUT data stream, as fast as we can and output
        # the received data to our User I/O and LEDS
        leds   = Cat(platform.request_optional("led", i, default=NullPin()).o for i in range(6))
        pmod_a = platform.request_optional("user_pmod", 0, default=NullPin(8))
        with m.If(stream_out_ep.stream.valid):
            m.d.comb += [
                leds.eq(stream_out_ep.stream.payload[2:8]),
                pmod_a.o.eq(stream_out_ep.stream.payload),
                pmod_a.oe.eq(1),
            ]


        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if self.fs_only else 0),
        ]

        return m


class USBInSuperSpeedTestDevice(Elaboratable):
    """ Simple example of a USB SuperSpeed device using the LUNA framework. """

    MAX_BULK_PACKET_SIZE = 1024

    def __init__(self, generate_clocks=True):
        self.generate_clocks = generate_clocks

    def create_descriptors(self):
        """ Create the descriptors we want to use for our device. """

        descriptors = SuperSpeedDeviceDescriptorCollection()

        #
        # We'll add the major components of the descriptors we we want.
        # The collection we build here will be necessary to create a standard endpoint.
        #

        # We'll need a device descriptor...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = 0x16d0
            d.idProduct          = 0xf3b

            # We're complying with the USB 3.2 standard.
            d.bcdUSB             = 3.2

            # USB3 requires this to be "9", to indicate 2 ** 9, or 512B.
            d.bMaxPacketSize0    = 9

            d.iManufacturer      = "LUNA"
            d.iProduct           = "SuperSpeed Bulk Test"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:
            c.bMaxPower        = 50

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor(add_default_superspeed=True) as e:
                    e.bEndpointAddress = 0x80 | BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.MAX_BULK_PACKET_SIZE

        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Generate our clock domains, if needed.
        if self.generate_clocks:
            m.submodules.clocks = platform.clock_domain_generator()

        # Create our core PIPE PHY. Since PHY configuration is per-board, we'll just ask
        # our platform for a pre-configured USB3 PHY.
        m.submodules.phy = phy = platform.create_usb3_phy()

        # Create our core SuperSpeed device.
        m.submodules.usb = usb = USBSuperSpeedDevice(phy=phy)

        # Add our standard control endpoint to the device.
        descriptors = self.create_descriptors()
        usb.add_standard_control_endpoint(descriptors)

        # Create our example bulk endpoint.
        stream_in_ep = SuperSpeedStreamInEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=self.MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_in_ep)

        # Create a simple, monotonically-increasing data stream, and connect that up to
        # to our streaming endpoint.
        counter   = Signal(16)
        stream_in = stream_in_ep.stream

        # Always provide our counter as the input to our stream; it will be consumed
        # whenever our stream endpoint can accept it.
        m.d.comb += [
            stream_in.data    .eq(counter),
            stream_in.valid   .eq(0b1111)
        ]

        # Increment our counter whenever our endpoint is accepting data.
        with m.If(stream_in.ready):
            m.d.ss += counter.eq(counter + 1)

        # Return our elaborated module.
        return m
