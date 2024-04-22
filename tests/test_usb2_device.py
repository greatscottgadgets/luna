#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test            import usb_domain_test_case
from luna.gateware.test.usb2       import USBDeviceTest

from luna.gateware.usb.usb2        import USBPacketID
from luna.gateware.usb.usb2.device import USBDevice

from usb_protocol.emitters         import DeviceDescriptorCollection
from usb_protocol.types            import DescriptorTypes

class FullDeviceTest(USBDeviceTest):
    """ :meta private: """

    FRAGMENT_UNDER_TEST = USBDevice
    FRAGMENT_ARGUMENTS = {'handle_clocking': False}

    def traces_of_interest(self):
        return (
            self.utmi.tx_data,
            self.utmi.tx_valid,
            self.utmi.rx_data,
            self.utmi.rx_valid,
        )

    def initialize_signals(self):

        # Keep our device from resetting.
        yield self.utmi.line_state.eq(0b01)

        # Have our USB device connected.
        yield self.dut.connect.eq(1)

        # Pretend our PHY is always ready to accept data,
        # so we can move forward quickly.
        yield self.utmi.tx_ready.eq(1)


    def provision_dut(self, dut):
        self.descriptors = descriptors = DeviceDescriptorCollection()

        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = 0x16d0
            d.idProduct          = 0xf3b

            d.iManufacturer      = "LUNA"
            d.iProduct           = "Test Device"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1

        # Provide a core configuration descriptor for testing.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x01
                    e.wMaxPacketSize   = 512

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x81
                    e.wMaxPacketSize   = 512

        dut.add_standard_control_endpoint(descriptors)


    @usb_domain_test_case
    def test_enumeration(self):

        # Reference enumeration process (quirks merged from Linux, macOS, and Windows):
        # - Read 8 bytes of device descriptor.
        # - Read 64 bytes of device descriptor.
        # - Set address.
        # - Read exact device descriptor length.
        # - Read device qualifier descriptor, three times.
        # - Read config descriptor (without subordinates).
        # - Read language descriptor.
        # - Read Windows extended descriptors. [optional]
        # - Read string descriptors from device descriptor (wIndex=language id).
        # - Set configuration.
        # - Read back configuration number and validate.


        # Read 8 bytes of our device descriptor.
        handshake, data = yield from self.get_descriptor(DescriptorTypes.DEVICE, length=8)
        self.assertEqual(handshake, USBPacketID.ACK)
        self.assertEqual(bytes(data), self.descriptors.get_descriptor_bytes(DescriptorTypes.DEVICE)[0:8])

        # Read 64 bytes of our device descriptor, no matter its length.
        handshake, data = yield from self.get_descriptor(DescriptorTypes.DEVICE, length=64)
        self.assertEqual(handshake, USBPacketID.ACK)
        self.assertEqual(bytes(data), self.descriptors.get_descriptor_bytes(DescriptorTypes.DEVICE))

        # Send a nonsense request, and validate that it's stalled.
        handshake, data = yield from self.control_request_in(0x80, 30, length=10)
        self.assertEqual(handshake, USBPacketID.STALL)

        # Send a set-address request; we'll apply an arbitrary address 0x31.
        yield from self.set_address(0x31)
        self.assertEqual(self.address, 0x31)

        # Read our device descriptor.
        handshake, data = yield from self.get_descriptor(DescriptorTypes.DEVICE, length=18)
        self.assertEqual(handshake, USBPacketID.ACK)
        self.assertEqual(bytes(data), self.descriptors.get_descriptor_bytes(DescriptorTypes.DEVICE))

        # Read our device qualifier descriptor.
        for _ in range(3):
            handshake, data = yield from self.get_descriptor(DescriptorTypes.DEVICE_QUALIFIER, length=10)
            self.assertEqual(handshake, USBPacketID.STALL)

        # Read our configuration descriptor (no subordinates).
        handshake, data = yield from self.get_descriptor(DescriptorTypes.CONFIGURATION, length=9)
        self.assertEqual(handshake, USBPacketID.ACK)
        self.assertEqual(bytes(data), self.descriptors.get_descriptor_bytes(DescriptorTypes.CONFIGURATION)[0:9])

        # Read our configuration descriptor (with subordinates).
        handshake, data = yield from self.get_descriptor(DescriptorTypes.CONFIGURATION, length=32)
        self.assertEqual(handshake, USBPacketID.ACK)
        self.assertEqual(bytes(data), self.descriptors.get_descriptor_bytes(DescriptorTypes.CONFIGURATION))

        # Read our string descriptors.
        for i in range(4):
            handshake, data = yield from self.get_descriptor(DescriptorTypes.STRING, index=i, length=255)
            self.assertEqual(handshake, USBPacketID.ACK)
            self.assertEqual(bytes(data), self.descriptors.get_descriptor_bytes(DescriptorTypes.STRING, index=i))

        # Set our configuration...
        status_pid = yield from self.set_configuration(1)
        self.assertEqual(status_pid, USBPacketID.DATA1)

        # ... and ensure it's applied.
        handshake, configuration = yield from self.get_configuration()
        self.assertEqual(handshake, USBPacketID.ACK)
        self.assertEqual(configuration, [1], "device did not accept configuration!")


class LongDescriptorTest(USBDeviceTest):
    """ :meta private: """

    FRAGMENT_UNDER_TEST = USBDevice
    FRAGMENT_ARGUMENTS = {'handle_clocking': False}

    def initialize_signals(self):

        # Keep our device from resetting.
        yield self.utmi.line_state.eq(0b01)

        # Have our USB device connected.
        yield self.dut.connect.eq(1)

        # Pretend our PHY is always ready to accept data,
        # so we can move forward quickly.
        yield self.utmi.tx_ready.eq(1)


    def provision_dut(self, dut):
        self.descriptors = descriptors = DeviceDescriptorCollection()

        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = 0x16d0
            d.idProduct          = 0xf3b

            d.iManufacturer      = "LUNA"
            d.iProduct           = "Test Device"
            d.iSerialNumber      = "1234"

            d.bNumConfigurations = 1

        # Provide a core configuration descriptor for testing.
        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                for n in range(15):

                    with i.EndpointDescriptor() as e:
                        e.bEndpointAddress = n
                        e.wMaxPacketSize   = 512

                    with i.EndpointDescriptor() as e:
                        e.bEndpointAddress = 0x80 | n
                        e.wMaxPacketSize   = 512

        dut.add_standard_control_endpoint(descriptors)

    @usb_domain_test_case
    def test_long_descriptor(self):
        descriptor = self.descriptors.get_descriptor_bytes(DescriptorTypes.CONFIGURATION)

        # Read our configuration descriptor (no subordinates).
        handshake, data = yield from self.get_descriptor(DescriptorTypes.CONFIGURATION, length=len(descriptor))
        self.assertEqual(handshake, USBPacketID.ACK)
        self.assertEqual(bytes(data), descriptor)
        self.assertEqual(len(data), len(descriptor))

    @usb_domain_test_case
    def test_descriptor_zlp(self):
        # Try requesting a long descriptor, but using a length that is a
        # multiple of the endpoint's maximum packet length. This should cause
        # the device to return some number of packets with the maximum packet
        # length, followed by a zero-length packet to terminate the
        # transaction.

        descriptor = self.descriptors.get_descriptor_bytes(DescriptorTypes.CONFIGURATION)

        # Try requesting a single and three max-sized packet.
        for factor in [1, 3]:
            request_length = self.max_packet_size_ep0 * factor
            handshake, data = yield from self.get_descriptor(DescriptorTypes.CONFIGURATION, length=request_length)
            self.assertEqual(handshake, USBPacketID.ACK)
            self.assertEqual(bytes(data), descriptor[0:request_length])
            self.assertEqual(len(data), request_length)
