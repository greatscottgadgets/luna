from nmigen                                   import Elaboratable, Module, Signal, Cat

from ...stream                                import StreamInterface
from ..usb2.device                            import USBDevice
from ..usb2.request                           import USBRequestHandler, StallOnlyRequestHandler
from ..usb2.endpoints.status                  import USBSignalInEndpoint

from usb_protocol.types                       import USBRequestType,USBTransferType
from usb_protocol.emitters                    import DeviceDescriptorCollection
from usb_protocol.emitters.descriptors.hid    import HIDDescriptor, HIDPrefix




class HIDDevice(Elaboratable):

    _STATUS_ENDPOINT_NUMBER = 1

    def __init__(self, *, bus, idVendor, idProduct,
        manufacturer_string="LUNA",
        product_string="HID Register Reader",
        serial_number=None, max_packet_size=64,
        hid_report=None,
        usage_page=0x01, usage=0x0):

        self._bus                 = bus
        self._idVendor            = idVendor
        self._idProduct           = idProduct
        self._manufacturer_string = manufacturer_string
        self._product_string      = product_string
        self._serial_number       = serial_number
        self._max_packet_size     = max_packet_size
        self._hid_report          = hid_report
        self._usage_page          = usage_page
        self._usage               = usage

        #
        # I/O port
        #
        self.connect = Signal()
        self.inputs = []

    def _int_to_le_bytes(self, i):
        for n in (1, 2, 4):
            try:
                return int.to_bytes(i, n, byteorder="little")
            except OverflowError:
                pass
        raise OverflowError("Value cannot be represented in 4 bytes")

    def add_input(self, signal, input_range=None, usage=0x0):
        if(input_range == None):
            shape = signal.shape()
            if(shape.signed):
                input_range = range(-(1 << (shape.width - 1)) + 1, 1 << (shape.width - 1))
            else:
                input_range = range(0, (1 << shape.width) - 1)
        self.inputs.append((signal, input_range, usage))


    def create_descriptors(self):
        descriptors = DeviceDescriptorCollection()
        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = self._idVendor
            d.idProduct          = self._idProduct

            d.iManufacturer      = self._manufacturer_string
            d.iProduct           = self._product_string
            d.iSerialNumber      = self._serial_number

            d.bNumConfigurations = 1
        with descriptors.ConfigurationDescriptor() as c:
            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                i.bInterfaceClass    = 0x03 # HID
                i.bInterfaceSubclass = 0x00 # No SubClass
                i.bInterfaceProtocol = 0x00 # No Protocol
                
                i.iInterface = 0x00

                hid_header = HIDDescriptor(descriptors)
                if self._hid_report:
                    hid_header.add_report_raw(self._hid_report)
                else:
                    hid_header.add_report_item(HIDPrefix.USAGE_PAGE, self._usage_page)
                    hid_header.add_report_item(HIDPrefix.USAGE, self._usage)
                    hid_header.add_report_item(HIDPrefix.COLLECTION, 0x01)
                    for (signal, input_range, usage) in self.inputs:
                        hid_header.add_report_item(HIDPrefix.LOGICAL_MIN, *self._int_to_le_bytes(input_range.start))
                        hid_header.add_report_item(HIDPrefix.LOGICAL_MAX, *self._int_to_le_bytes(input_range.stop))
                        hid_header.add_report_item(HIDPrefix.REPORT_SIZE, *self._int_to_le_bytes(signal.shape().width))
                        hid_header.add_report_item(HIDPrefix.REPORT_COUNT, 0x01),
                        hid_header.add_report_item(HIDPrefix.USAGE, usage)
                        hid_header.add_input_item()
                    hid_header.add_report_item(HIDPrefix.END_COLLECTION)

                i.add_subordinate_descriptor(hid_header)

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | self._STATUS_ENDPOINT_NUMBER
                    e.bmAttributes     = USBTransferType.INTERRUPT
                    e.wMaxPacketSize   = self._max_packet_size
                    e.bInterval        = 1

        return descriptors

    def elaborate(self, platform):
        m = Module()

        # Create our core USB device, and add a standard control endpoint.
        m.submodules.usb = usb = USBDevice(bus=self._bus)
        _control_ep = usb.add_standard_control_endpoint(self.create_descriptors())

        # Cram all the registers into a single report
        statuses = Cat([signal for (signal, _input_range, _usage) in self.inputs])

        # Create an endpoint to emit our report every time we get polled
        status_ep = USBSignalInEndpoint(width=statuses.shape().width, endpoint_number=1, endianness="little")
        usb.add_endpoint(status_ep)

        # Connect our USB device
        m.d.comb += [
            status_ep.signal.eq(statuses),
            usb.connect     .eq(self.connect)
        ]

        return m
