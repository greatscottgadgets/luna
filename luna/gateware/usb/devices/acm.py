#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Pre-made gateware that implements CDC-ACM serial. """

from nmigen                            import Elaboratable, Module, Signal

from ...stream                         import StreamInterface
from ..usb2.device                     import USBDevice
from ..usb2.endpoints.stream           import USBStreamInEndpoint, USBStreamOutEndpoint

from usb_protocol.emitters             import DeviceDescriptorCollection
from usb_protocol.emitters.descriptors import cdc


class USBSerialDevice(Elaboratable):
    """ Device that acts as a CDC-ACM 'serial converter'.

    Exposes a stream interface.

    Attributes
    ----------
    connect: Signal(), input
        When asserted, the USB-to-serial device will be presented to the host
        and allowed to communicate.
    rx: StreamInterface(), output stream
        A stream carrying data received from the host.
    tx: StreamInterface(), input stream
        A stream carrying data to be transmitted to the host.

    Parameters
    ----------
    bus: Record()
        The raw input record that provides our USB connection. Should be a connection to a USB PHY,
        SerDes, or raw USB lines as described at: https://luna.readthedocs.io/en/latest/custom_hardware.html.
    idVendor: int, <65536
        The Vendor ID that should be presented for the relevant USB device.
    idProduct: int, <65536
        The Product ID that should be presented for the relevant USB device.

    manufacturer_string: str, optional
        A string describing this device's manufacturer.
    product_str: str, optional
        A string describing this device.
    serial_number: str, optional
        A string describing this device's serial number.

    max_packet_size: int in {64, 246, 512}, optional
        The maximum packet size for communications.
    """

    _STATUS_ENDPOINT_NUMBER = 3
    _DATA_ENDPOINT_NUMBER   = 4

    def __init__(self, *, bus, idVendor, idProduct,
            manufacturer_string="LUNA",
            product_string="USB-to-serial",
            serial_number=None, max_packet_size=64):

        self._bus                 = bus
        self._idVendor            = idVendor
        self._idProduct           = idProduct
        self._manufacturer_string = manufacturer_string
        self._product_string      = product_string
        self._serial_number       = serial_number
        self._max_packet_size     = max_packet_size

        #
        # I/O port
        #
        self.connect = Signal()
        self.rx      = StreamInterface()
        self.tx      = StreamInterface()


    def create_descriptors(self):
        """ Creates the descriptors that describe our serial topology. """

        descriptors = DeviceDescriptorCollection()

        # Create a device descriptor with our user parameters...
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = self._idVendor
            d.idProduct          = self._idProduct

            d.iManufacturer      = self._manufacturer_string
            d.iProduct           = self._product_string
            d.iSerialNumber      = self._serial_number

            d.bNumConfigurations = 1


        # ... and then describe our CDC-ACM setup.
        with descriptors.ConfigurationDescriptor() as c:

            # First, we'll describe the Communication Interface, which contains most
            # of our description; but also an endpoint that does effectively nothing in
            # our case, since we don't have interrupts we want to send up to the host.
            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber   = 0

                i.bInterfaceClass    = 0x02 # CDC
                i.bInterfaceSubclass = 0x02 # ACM
                i.bInterfaceProtocol = 0x02 # AT commands / UART

                # Provide the default CDC version.
                i.add_subordinate_descriptor(cdc.HeaderDescriptorEmitter())

                # ... specify our interface associations ...
                union = cdc.UnionFunctionalDescriptorEmitter()
                union.bControlInterface      = 0
                union.bSubordinateInterface0 = 1
                i.add_subordinate_descriptor(union)

                # ... and specify the interface that'll carry our data...
                call_management = cdc.CallManagementFunctionalDescriptorEmitter()
                call_management.bDataInterface = 1
                i.add_subordinate_descriptor(call_management)

                # CDC communications endpoint
                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | self._STATUS_ENDPOINT_NUMBER
                    e.bmAttributes     = 0x03
                    e.wMaxPacketSize   = self._max_packet_size
                    e.bInterval        = 11

            # Finally, we'll describe the communications interface, which just has the
            # endpoints for our data in and out.
            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber   = 1
                i.bInterfaceClass    = 0x0a # CDC data
                i.bInterfaceSubclass = 0x00
                i.bInterfaceProtocol = 0x00

                # Data IN to host (tx, from our side)
                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | self._DATA_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self._max_packet_size

                # Data OUT from host (rx, from our side)
                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = self._DATA_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = self._max_packet_size

        return descriptors


    def elaborate(self, platform):
        m = Module()

        # Create our core USB device, and add a standard control endpoint.
        m.submodules.usb = usb = USBDevice(bus=self._bus)
        usb.add_standard_control_endpoint(self.create_descriptors())

        # Create our status/communications endpoint; but don't ever drive its stream.
        # This should be optimized down to an endpoint that always NAKs.
        serial_status_ep = USBStreamInEndpoint(
            endpoint_number=self._STATUS_ENDPOINT_NUMBER,
            max_packet_size=self._max_packet_size
        )
        usb.add_endpoint(serial_status_ep)

        # Create an endpoint for serial rx...
        serial_rx_endpoint = USBStreamOutEndpoint(
            endpoint_number=0x04,
            max_packet_size=self._max_packet_size,
        )
        usb.add_endpoint(serial_rx_endpoint)

        # ... and one for serial tx.
        serial_tx_endpoint = USBStreamInEndpoint(
            endpoint_number=0x04,
            max_packet_size=self._max_packet_size
        )
        usb.add_endpoint(serial_tx_endpoint)

        # Connect up our I/O.
        m.d.comb += [
            serial_tx_endpoint.stream  .connect(self.tx),
            self.rx                    .connect(serial_rx_endpoint.stream),
            usb.connect                .eq(self.connect)
        ]

        return m

