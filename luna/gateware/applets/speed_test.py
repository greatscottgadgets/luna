from amaranth                import *
from usb_protocol.emitters   import DeviceDescriptorCollection, SuperSpeedDeviceDescriptorCollection

from luna.usb2               import USBDevice, USBStreamInEndpoint
from luna.usb3               import USBSuperSpeedDevice, SuperSpeedStreamInEndpoint

VENDOR_ID  = 0x16d0
PRODUCT_ID = 0x0f3b

BULK_ENDPOINT_NUMBER = 1


class USBInSpeedTestDevice(Elaboratable):
    """ Simple device that sends data to the host as fast as hardware can. """

    def __init__(self, fs_only=False, phy=None):
        self.fs_only = fs_only
        self.phy = phy
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
            d.idVendor           = VENDOR_ID
            d.idProduct          = PRODUCT_ID

            d.iManufacturer      = "LUNA"
            d.iProduct           = "IN speed test"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        # ... and a description of the USB configuration we'll provide.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self.max_bulk_packet_size


        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

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

        # Add a stream endpoint to our device.
        stream_ep = USBStreamInEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=self.max_bulk_packet_size
        )
        usb.add_endpoint(stream_ep)

        # Send entirely zeroes, as fast as we can.
        m.d.comb += [
            stream_ep.stream.valid    .eq(1),
            stream_ep.stream.payload  .eq(0)
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

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

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
