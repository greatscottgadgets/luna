#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test               import LunaSSGatewareTestCase, ss_domain_test_case

from luna.gateware.usb.usb3.application.request import SuperSpeedSetupDecoder
from usb_protocol.types     import USBRequestType, USBRequestRecipient

class SuperSpeedSetupDecoderTest(LunaSSGatewareTestCase):
    FRAGMENT_UNDER_TEST = SuperSpeedSetupDecoder

    @ss_domain_test_case
    def test_setup_parse(self):
        dut   = self.dut
        sink  = dut.sink
        setup = dut.packet

        # Mark our data as always valid SETUP data.
        yield dut.header_in.setup.eq(1)
        yield sink.valid.eq(0b1111)

        # Provide our first word...
        yield sink.first.eq(1)
        yield sink.last .eq(0)
        yield sink.data .eq(0x2211AAC1)
        yield

        # ... then our second ...
        yield sink.first.eq(0)
        yield sink.last .eq(1)
        yield sink.data .eq(0x00043344)
        yield

        # ... then mark our packet as good.
        yield from self.pulse(dut.rx_good)
        yield

        # Finally, check that our fields have been parsed properly.
        self.assertEqual((yield setup.is_in_request), 1)
        self.assertEqual((yield setup.type),          USBRequestType.VENDOR)
        self.assertEqual((yield setup.recipient),     USBRequestRecipient.INTERFACE)
        self.assertEqual((yield setup.request),       0xAA)
        self.assertEqual((yield setup.value),         0x2211)
        self.assertEqual((yield setup.index),         0x3344)
        self.assertEqual((yield setup.length),        4)

