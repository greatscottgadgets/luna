#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import logging
import os
import time
import usb1

from amaranth                          import Elaboratable, Module, Signal

from luna                              import top_level_cli, configure_default_logging
from luna.usb2                         import USBDevice, USBStreamInEndpoint, USBStreamOutEndpoint
from luna.gateware.stream.generator    import StreamSerializer
from luna.gateware.usb.request.control import ControlRequestHandler
from luna.gateware.usb.stream          import USBInStreamInterface

from usb_protocol.types                import USBRequestRecipient, USBRequestType
from usb_protocol.emitters             import DeviceDescriptorCollection

# use pid.codes Test PID
VID = 0x1209
PID = 0x0001

BULK_ENDPOINT_NUMBER = 1
MAX_BULK_PACKET_SIZE = 512

COUNTER_MAX = 251
GET_OUT_COUNTER_VALID = 0

out_counter_valid = Signal(reset=1)

class VendorRequestHandler(ControlRequestHandler):

    REQUEST_SET_LEDS = 0

    def elaborate(self, platform):
        m = Module()

        interface         = self.interface
        setup             = self.interface.setup

        # Transmitter for small-constant-response requests
        m.submodules.transmitter = transmitter = \
            StreamSerializer(data_length=1, domain="usb", stream_type=USBInStreamInterface, max_length_width=1)
        #
        # Vendor request handlers.
        with m.FSM(domain="usb"):
            with m.State('IDLE'):
                vendor = setup.type == USBRequestType.VENDOR
                with m.If(
                    setup.received & \
                    (setup.type == USBRequestType.VENDOR) & \
                    (setup.recipient == USBRequestRecipient.INTERFACE) & \
                    (setup.index == 0)):
                    with m.Switch(setup.request):
                        with m.Case(GET_OUT_COUNTER_VALID):
                            m.d.comb += interface.claim.eq(1)
                            m.next = 'GET_OUT_COUNTER_VALID'
                            pass

            with m.State('GET_OUT_COUNTER_VALID'):
                m.d.comb += interface.claim.eq(1)
                self.handle_simple_data_request(m, transmitter, out_counter_valid, length=1)

        return m


class ClearHaltTestDevice(Elaboratable):


    def create_descriptors(self):

        descriptors = DeviceDescriptorCollection()

        with descriptors.DeviceDescriptor() as d:
            d.idVendor           = VID
            d.idProduct          = PID

            d.iManufacturer      = "LUNA"
            d.iProduct           = "Clear Endpoint Halt Test"
            d.iSerialNumber      = "no serial"

            d.bNumConfigurations = 1


        with descriptors.ConfigurationDescriptor() as c:

            with c.InterfaceDescriptor() as i:
                i.bInterfaceNumber = 0

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = 0x80 | BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = MAX_BULK_PACKET_SIZE

                with i.EndpointDescriptor() as e:
                    e.bEndpointAddress = BULK_ENDPOINT_NUMBER
                    e.wMaxPacketSize   = MAX_BULK_PACKET_SIZE


        return descriptors


    def elaborate(self, platform):
        m = Module()

        m.submodules.car = platform.clock_domain_generator()

        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        descriptors = self.create_descriptors()
        control_ep = usb.add_standard_control_endpoint(descriptors)

        control_ep.add_request_handler(VendorRequestHandler())

        stream_in_ep = USBStreamInEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_in_ep)

        stream_out_ep = USBStreamOutEndpoint(
            endpoint_number=BULK_ENDPOINT_NUMBER,
            max_packet_size=MAX_BULK_PACKET_SIZE
        )
        usb.add_endpoint(stream_out_ep)

        # Generate a counter on the IN endpoint.
        in_counter = Signal(8)
        with m.If(stream_in_ep.stream.ready):
            m.d.usb += in_counter.eq(in_counter + 1)
            with m.If(in_counter == COUNTER_MAX):
                m.d.usb += in_counter.eq(0)

        # Expect a counter on the OUT endpoint, and verify that it is contiguous.
        prev_out_counter = Signal(8, reset=COUNTER_MAX)
        with m.If(stream_out_ep.stream.valid):
            out_counter = stream_out_ep.stream.payload
            counter_increase = out_counter == (prev_out_counter + 1)
            counter_wrap = (out_counter == 0) & (prev_out_counter == COUNTER_MAX)
            with m.If(~counter_increase & ~counter_wrap):
                m.d.usb += out_counter_valid.eq(0)

            m.d.usb += prev_out_counter.eq(out_counter)

        m.d.comb += [
            stream_in_ep.stream.valid    .eq(1),
            stream_in_ep.stream.payload  .eq(in_counter),

            stream_out_ep.stream.ready   .eq(1),
        ]

        # Connect our device as a high speed device by default.
        m.d.comb += [
            usb.connect          .eq(1),
            usb.full_speed_only  .eq(1 if os.getenv('LUNA_FULL_ONLY') else 0),
        ]

        return m

def test_clear_halt():
    with usb1.USBContext() as context:
        device = context.openByVendorIDAndProductID(VID, PID)

        # Read the first packet which should have a DATA0 PID, next we expect DATA1.
        packet = device.bulkRead(BULK_ENDPOINT_NUMBER, MAX_BULK_PACKET_SIZE)
        # Send clear halt, this resets both sides to DATA0.
        device.clearHalt(usb1.ENDPOINT_IN | BULK_ENDPOINT_NUMBER)
        # Read another packet. If the PID doesn't match what we epxect,
        # then the host will assume it was a retransmission of the last one and drop it.
        packet += device.bulkRead(BULK_ENDPOINT_NUMBER, MAX_BULK_PACKET_SIZE)

        # Check that the counter is contiguous across all received data, making sure we didn't drop a packet.
        for i in range(1, len(packet)):
            if packet[i] == packet[i-1] + 1:
                pass
            elif packet[i] == 0 and packet[i-1] == COUNTER_MAX:
                pass
            else:
                print(f"IN test fail {i} {packet[i]} {packet[i-1]}")
                return

        print("IN OK")

        # Generate three packets worth of counter data, the gateware will verify that it is contiguous.
        data = bytes(i % (COUNTER_MAX+1) for i in range(MAX_BULK_PACKET_SIZE*3))
        # Send DATA0, device should expect DATA1 next.
        device.bulkWrite(BULK_ENDPOINT_NUMBER, data[:MAX_BULK_PACKET_SIZE])
        # Reset both sides to DATA0.
        device.clearHalt(usb1.ENDPOINT_OUT | BULK_ENDPOINT_NUMBER)
        # Send two packets. If the first packet doesn't match,
        # it'll be dropped and another is required to let the gateware check the counter.
        device.bulkWrite(BULK_ENDPOINT_NUMBER, data[MAX_BULK_PACKET_SIZE:])

        # Read back the out_counter_valid register to check for success.
        request_type = usb1.REQUEST_TYPE_VENDOR | usb1.RECIPIENT_INTERFACE | usb1.ENDPOINT_IN
        if device.controlRead(request_type, GET_OUT_COUNTER_VALID, 0, 0, 1)[0] == 1:
            print("OUT OK")
        else:
            print("OUT FAIL")


if __name__ == "__main__":
    configure_default_logging()

    # If our environment is suggesting we rerun tests without rebuilding, do so.
    if os.getenv('LUNA_RERUN_TEST'):
        logging.info("Running speed test without rebuilding...")

    # Otherwise, rebuild.
    else:
        device = top_level_cli(ClearHaltTestDevice)

        # Give the device a moment to connect.
        if device is not None:
            logging.info("Giving the device time to connect...")
            time.sleep(5)

    test_clear_halt()