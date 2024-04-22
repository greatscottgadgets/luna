#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test                                 import LunaUSBGatewareTestCase, usb_domain_test_case

from luna.gateware.usb.usb2.descriptor import GetDescriptorHandlerBlock, DeviceDescriptorCollection, StandardDescriptorNumbers

class GetDescriptorHandlerBlockTest(LunaUSBGatewareTestCase):
    descriptors = DeviceDescriptorCollection()

    with descriptors.DeviceDescriptor() as d:
        d.bcdUSB             = 2.00
        d.idVendor           = 0x1234
        d.idProduct          = 0x4567
        d.iManufacturer      = "Manufacturer"
        d.iProduct           = "Product"
        d.iSerialNumber      = "ThisSerialNumberIsResultsInADescriptorLongerThan64Bytes"
        d.bNumConfigurations = 1

        with descriptors.ConfigurationDescriptor() as c:
            c.bmAttributes = 0xC0
            c.bMaxPower = 50

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber   = 0
                i.bInterfaceClass    = 0x02
                i.bInterfaceSubclass = 0x02
                i.bInterfaceProtocol = 0x01

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x81
                    e.bmAttributes     = 0x03
                    e.wMaxPacketSize   = 64
                    e.bInterval        = 11

    # HID Descriptor (Example E.8 of HID specification)
    descriptors.add_descriptor(b'\x09\x21\x01\x01\x00\x01\x22\x00\x32')

    FRAGMENT_UNDER_TEST = GetDescriptorHandlerBlock
    FRAGMENT_ARGUMENTS = {"descriptor_collection": descriptors}

    def traces_of_interest(self):
        dut = self.dut
        return (dut.value, dut.length, dut.start_position, dut.start, dut.stall,
                dut.tx.ready, dut.tx.first, dut.tx.last, dut.tx.payload, dut.tx.valid)

    def _test_descriptor(self, type_number, index, raw_descriptor, start_position, max_length, delay_ready=0):
        """ Triggers a read and checks if correct data is transmitted. """

        # Set a defined start before starting
        yield self.dut.tx.ready.eq(0)
        yield

        # Set up request
        yield self.dut.value.word_select(1, 8).eq(type_number)  # Type
        yield self.dut.value.word_select(0, 8).eq(index)  # Index
        yield self.dut.length.eq(max_length)
        yield self.dut.start_position.eq(start_position)
        yield self.dut.tx.ready.eq(1 if delay_ready == 0 else 0)
        yield self.dut.start.eq(1)
        yield

        yield self.dut.start.eq(0)

        yield from self.wait_until(self.dut.tx.valid, timeout=100)

        if delay_ready > 0:
            for _ in range(delay_ready-1):
                yield
            yield self.dut.tx.ready.eq(1)
            yield

        max_packet_length = 64
        expected_data = raw_descriptor[start_position:]
        expected_bytes = min(len(expected_data), max_length-start_position, max_packet_length)

        if expected_bytes == 0:
            self.assertEqual((yield self.dut.tx.first), 0)
            self.assertEqual((yield self.dut.tx.last),  1)
            self.assertEqual((yield self.dut.tx.valid), 1)
            self.assertEqual((yield self.dut.stall),    0)
            yield

        else:
            for i in range(expected_bytes):
                self.assertEqual((yield self.dut.tx.first),   1 if (i == 0) else 0)
                self.assertEqual((yield self.dut.tx.last),    1 if (i == expected_bytes - 1) else 0)
                self.assertEqual((yield self.dut.tx.valid),   1)
                self.assertEqual((yield self.dut.tx.payload), expected_data[i])
                self.assertEqual((yield self.dut.stall),      0)
                yield

        self.assertEqual((yield self.dut.tx.valid), 0)

    def _test_stall(self, type_number, index, start_position, max_length):
        """ Triggers a read and checks if correctly stalled. """

        yield self.dut.value.word_select(1, 8).eq(type_number)  # Type
        yield self.dut.value.word_select(0, 8).eq(index)  # Index
        yield self.dut.length.eq(max_length)
        yield self.dut.start_position.eq(start_position)
        yield self.dut.tx.ready.eq(1)
        yield self.dut.start.eq(1)
        yield

        yield self.dut.start.eq(0)

        cycles_passed = 0
        timeout = 100

        while not (yield self.dut.stall):
            self.assertEqual((yield self.dut.tx.valid), 0)
            yield

            cycles_passed += 1
            if timeout and cycles_passed > timeout:
                raise RuntimeError(f"Timeout waiting for stall!")

    @usb_domain_test_case
    def test_all_descriptors(self):
        for type_number, index, raw_descriptor in self.descriptors:
            yield from self._test_descriptor(type_number, index, raw_descriptor, 0, len(raw_descriptor))
            yield from self._test_descriptor(type_number, index, raw_descriptor, 0, len(raw_descriptor), delay_ready=10)

    @usb_domain_test_case
    def test_all_descriptors_with_offset(self):
        for type_number, index, raw_descriptor in self.descriptors:
            if len(raw_descriptor) > 1:
                yield from self._test_descriptor(type_number, index, raw_descriptor, 1, len(raw_descriptor))

    @usb_domain_test_case
    def test_all_descriptors_with_length(self):
        for type_number, index, raw_descriptor in self.descriptors:
            if len(raw_descriptor) > 1:
                yield from self._test_descriptor(type_number, index, raw_descriptor, 0, min(8, len(raw_descriptor)-1))
                yield from self._test_descriptor(type_number, index, raw_descriptor, 0, min(8, len(raw_descriptor)-1), delay_ready=10)

    @usb_domain_test_case
    def test_all_descriptors_with_offset_and_length(self):
        for type_number, index, raw_descriptor in self.descriptors:
            if len(raw_descriptor) > 1:
                yield from self._test_descriptor(type_number, index, raw_descriptor, 1, min(8, len(raw_descriptor)-1))

    @usb_domain_test_case
    def test_all_descriptors_with_zero_length(self):
        for type_number, index, raw_descriptor in self.descriptors:
            yield from self._test_descriptor(type_number, index, raw_descriptor, 0, 0)

    @usb_domain_test_case
    def test_unavailable_descriptor(self):
        yield from self._test_stall(StandardDescriptorNumbers.STRING, 100, 0, 64)

    @usb_domain_test_case
    def test_unavailable_index_type(self):
        # Unavailable index in between
        yield from self._test_stall(0x10, 0, 0, 64)

        # Index after last used type
        yield from self._test_stall(0x42, 0, 0, 64)
