#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Full-device test harnesses for USB2. """

from usb_protocol.types import USBStandardRequests, USBPacketID

from .                  import LunaGatewareTestCase

from .contrib           import usb_packet
from ..interface.utmi   import UTMIInterface

class USBDeviceTest(LunaGatewareTestCase):
    """ Test case strap for UTMI-connected devices. """

    # Use only the USB clock domain; ignore the sync one unless overridden.
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY  = 60e6

    # The name of the argument to the DUT that will accept our UTMI bus.
    UTMI_BUS_ARGUMENT = 'bus'

    # The maximum number of NAKs we should allow in a loop before we bail out.
    # Keeping this reasonable prevents the simulation from running indefinitely.
    MAX_NAKS = 100

    def instantiate_dut(self):
        self.utmi    = UTMIInterface()

        # Vitals about the device.
        self.address             = 0
        self.max_packet_size_ep0 = 64

        # Always pass in the UTMI bus.
        arguments = self.FRAGMENT_ARGUMENTS.copy()
        arguments[self.UTMI_BUS_ARGUMENT] = self.utmi

        dut =  self.FRAGMENT_UNDER_TEST(**arguments)
        self.provision_dut(dut)

        return dut


    def provision_dut(self, dut):
        """ Hook that allows us to add any desired properties to the DUT before simulation.

        This method is called before initial elaboration; so functions that modify devices
        before elaboration can be used.
        """
        pass


    def provide_byte(self, byte):
        """ Provides a given byte on the UTMI receive data for one cycle. """
        yield self.utmi.rx_data.eq(byte)
        yield


    def start_packet(self, *, set_rx_valid=True):
        """ Starts a UTMI packet receive. """
        yield self.utmi.rx_active.eq(1)

        if set_rx_valid:
            yield self.utmi.rx_valid.eq(1)

        yield


    def end_packet(self):
        """ Starts a UTMI packet receive. """
        yield self.utmi.rx_active.eq(0)
        yield self.utmi.rx_valid.eq(0)
        yield


    def provide_packet(self, *octets, cycle_after=True):
        """ Provides an entire packet transaction at once. """

        yield from self.start_packet()

        for b in octets:
            yield from self.provide_byte(b)

        yield from self.end_packet()

        if cycle_after:
            yield


    @staticmethod
    def bits_to_octets(bits):
        """ Converts a string of bits to octets.

        For compatibility with antmicro's USB-testbench functions.
        """

        bits   = bits[:]
        octets = []

        assert (len(bits) % 8) == 0

        while bits:
            # Grab an octet worth of bits..
            octet_bits = bits[0:8][::-1]
            bits = bits[8:]

            # ... and parse it.
            octet = int(octet_bits, 2)
            octets.append(octet)

        return octets


    def provide_bits(self, bits, cycle_after=True):
        """ Provides an entire packet transaction at once; accepts bits. """

        octets = self.bits_to_octets(bits)
        yield from self.provide_packet(*octets, cycle_after=cycle_after)



    def send_token(self, pid, *, endpoint=0, address=None):
        """ Issues a token packet to the simulated USB device.

        Parameters:
            pid      -- The PID of the packet to be sent.
            endpoint -- The endpoint on which the token should be sent.
            address  -- The address of the device to be targeted.
                        If omitted, the most recently set-address'd address is used.
        """

        # Grab the raw bits that make up our token from the Antmicro library...
        address = address if address else self.address
        bits    = usb_packet.token_packet(pid, address, endpoint)

        # ... and issue them ourselves.
        yield from self.provide_bits(bits)



    def send_data(self, pid, *octets):
        """ Sends a data packet to the simulated USB device.

        Parameters:
            pid  -- The PID to send the provided packet with.
            *data -- The data to be sent.
        """

        bits = usb_packet.data_packet(pid, octets)
        yield from self.provide_bits(bits)




    def send_handshake(self, pid):
        """ Issues a handshake packet to the simulated USB device.

        Parameters:
            pid      -- The PID of the packet to be sent.
        """

        # Ensure we have an USBPacketID-wrapped PID.
        pid = USBPacketID(pid)
        yield from self.provide_packet(pid.byte())




    def receive_packet(self, as_bytes=True, timeout=1000):
        """ Receives a collection of data from the USB bus. """

        data = []

        # Mark us as ready to receive data.
        yield self.utmi.tx_ready.eq(1)
        yield

        # Wait for the TX line to be valid.
        yield from self.wait_until(self.utmi.tx_valid, timeout=timeout)

        # For as long as tx_valid is asserted, capture data.
        while (yield self.utmi.tx_valid):
            data.append((yield self.utmi.tx_data))
            yield

        # Mark us as ready to receive data.
        yield self.utmi.tx_ready.eq(0)

        return bytes(data) if as_bytes else data


    #
    # More complex transaction helpers.
    #

    def interpacket_delay(self):
        """ Waits for a period appropriate between each packet. """

        # We'll use a shorter value than real interpacket delays here,
        # to speed up simulation. This can be tuned longer if necessary.
        # A spec-valued length would be 10 for a FS device, or 1 for a HS.
        yield from self.advance_cycles(1)


    def out_transaction(self, *octets, endpoint=0, token_pid=USBPacketID.OUT,
        data_pid=USBPacketID.DATA0, expect_handshake=None):
        """ Performs an OUT transaction.

        Parameters:
            *octets          -- The data to send.
            endpoint         -- The endpoint on which to send the relevant data.
            token_pid        -- The token PID to send. Defaults to OUT.
            data_pid         -- The data PID to send. Defalts to DATA0.
            expect_handshake -- If provided, we'll assert that a given handshake is provided.

        Returns the handshake received.
        """

        # Issue the token...
        yield from self.send_token(token_pid, endpoint=endpoint)
        yield from self.interpacket_delay()

        # ... issue our DATA packet...
        yield from self.send_data(data_pid, *octets)

        # ... and receive our handshake.
        data = yield from self.receive_packet()

        # If we expect the SETUP packet to be ACK'd, validate that.
        if expect_handshake:
            self.assertEqual(USBPacketID.from_byte(data), expect_handshake)

        yield from self.interpacket_delay()
        return USBPacketID.from_byte(data)



    def out_transfer(self, *octets, endpoint=0, data_pid=USBPacketID.DATA0, max_packet_size=64):
        """ Performs an OUT transaction.

        Parameters:
            *octets          -- The data to send.
            endpoint         -- The endpoint on which to send the relevant data.
            data_pid         -- The first data PID to send. Defalts to DATA0.
            max_packet_size  -- The maximum packet size for the current endpoint.

        Returns the final handshake received.
        """

        to_send  = octets[:]

        # If we're going to send all max-packet-length sized packet,
        # we'll add a ZLP.
        send_zlp = (len(octets) % max_packet_size) == 0

        while to_send:

            # Pull a packet out of the send queue...
            packet = to_send[0:max_packet_size]

            # ... and try to send it.
            handshake = yield from self.out_transaction(endpoint=endpoint, data_pid=data_pid, *packet)

            # If we're stalled, abort immediately.
            if handshake == USBPacketID.STALL:
                return USBPacketID.STALL

            # If our packet is NAK'd, don't continue.
            if handshake == USBPacketID.NAK:
                continue

            # Otherwise, advance in the stream...
            to_send = to_send[max_packet_size:]

            # ... and toggle DATA PIDs.
            data_pid = USBPacketID.DATA1 if (data_pid == USBPacketID.DATA0) else USBPacketID.DATA0


        # If we're going to send a ZLP, send it.
        if send_zlp:
            handshake = USBPacketID.NAK
            while handshake == USBPacketID.NAK:
                handshake = yield from self.out_transaction(endpoint=endpoint, data_pid=data_pid)

        return handshake



    def in_transaction(self, endpoint=0, data_pid=None, handshake=USBPacketID.ACK):
        """ Performs an IN transaction.

        Parameters:
            endpoint    -- The endpoint on which to fetch the relevant data.
            data_pid    -- The data PID to expect, or None if we don't are.
            handshake   -- The response we should give after receiving data.

        Returns:
            handshake   -- The handshake retrieved in response.
            data        -- A list of octets received.
        """

        # Issue the IN token...
        yield from self.send_token(USBPacketID.IN, endpoint=endpoint)

        # ... receive our response...
        result = yield from self.receive_packet()
        try:
            pid, *data, crc_low, crc_high = result

        # If we can't unpack the response, just return the PID.
        except ValueError:
            return USBPacketID.from_int(result[0]), None

        # ... validate its CRC...
        expected_crc = usb_packet.crc16(data)
        self.assertEqual([crc_low, crc_high], expected_crc)

        # ... validate pid toggling, if desired...
        if data_pid:
            self.assertEqual(pid, data_pid.byte())

        # ... and issue our handshake.
        yield from self.interpacket_delay()
        yield from self.send_handshake(handshake)

        yield from self.interpacket_delay()
        return USBPacketID.from_int(pid), data


    def in_transfer(self, endpoint=0, data_pid=None, handshake=USBPacketID.ACK):
        """ Performs an IN transaction.

        Parameters:
            endpoint    -- The endpoint on which to fetch the relevant data.
            data_pid    -- The data PID to expect, or None if we don't are.
            handshake   -- The response we should give after receiving data.

        Returns:
            handshake   -- The last data handshake received.
            data        -- A list of octets received.
        """

        naks = 0
        data = []

        while True:
            pid, packet = yield from self.in_transaction(
                endpoint=0, data_pid=data_pid, handshake=USBPacketID.ACK)

            # If we were NAK'd, try again.
            if pid == USBPacketID.NAK:
                naks += 1
                self.assertLess(naks, self.MAX_NAKS)

                continue

            # If we were stalled, abort here.
            if pid == USBPacketID.STALL:
                return pid, None

            # Add the given packet to our transaction.
            data.extend(packet)

            # Swap to expecting the next packet ID.
            data_pid = USBPacketID.DATA1 if (data_pid == USBPacketID.DATA0) else USBPacketID.DATA0

            # If this is a short packet, stop receiving.
            if len(packet) < self.max_packet_size_ep0:
                break

        return pid, data


    def setup_transaction(self, request_type, request, value=0, index=0, length=0):
        """ Sends a SETUP transaction. All arguments match their SETUP packet definitions.

        Returns the handshake received.
        """

        def split(arg):
            """ Convenience function that splits a setup parameter. """
            high = arg >> 8
            low  = arg & 0xFF

            return low, high

        # ... issue our DATA token...
        response = yield from self.out_transaction(
            request_type, request, *split(value), *split(index), *split(length),
            token_pid=USBPacketID.SETUP, expect_handshake=USBPacketID.ACK
        )

        return response


    def control_interphase_delay(self):
        """ Waits for a period appropriate between each delays. """

        # This is shorter than would be normal, in order to speed up simulation.
        # If necessary, this can be extended arbitrarily.
        yield from self.advance_cycles(1)


    def control_request_in(self, request_type, request, value=0, index=0, length=0):
        """ Performs an IN control request, and returns the results.

        Arguments match the SETUP packets.

        Returns:
            handshake -- The handshake value returned.
            data      -- A list of octets returned.
        """

        naks = 0

        # If we don't have a data phase, treat this identically to an OUT control request.
        if length == 0:
            response = yield from self.control_request_out(request_type, request,
                value=value, index=index)
            return response

        #
        # Issue the Setup phase.
        #
        yield from self.setup_transaction(request_type, request, value, index, length)
        yield from self.control_interphase_delay()

        #
        # Issue the Data phase.
        #
        pid, packet = yield from self.in_transfer(data_pid=USBPacketID.DATA1)
        if pid == USBPacketID.STALL:
            return pid, None

        #
        # Issue the Status phase.
        #
        yield from self.control_interphase_delay()

        # Read until we get a status other than a NAK.
        handshake = USBPacketID.NAK
        while handshake == USBPacketID.NAK:
            naks += 1
            self.assertLess(naks, self.MAX_NAKS)

            handshake = yield from self.out_transaction(data_pid=USBPacketID.DATA1)


        # Finally, return our handshake and our data.
        return handshake, packet


    def control_request_out(self, request_type, request, value=0, index=0, data=()):
        """ Performs an OUT control request, and returns the results.

        Arguments match the SETUP packets.
        """

        naks = 0

        #
        # Issue the Setup phase.
        #
        yield from self.setup_transaction(request_type, request, value, index, len(data))
        yield from self.control_interphase_delay()


        #
        # Issue the Data phase, if we have one.
        #
        if data:
            pid = yield from self.out_transfer(data_pid=USBPacketID.DATA1, *data)
            if pid == USBPacketID.STALL:
                return pid


        #
        # Issue the Status phase.
        #
        yield from self.control_interphase_delay()

        # We'll perform an IN transfer, and expect a ZLP back.
        pid = USBPacketID.NAK
        while pid == USBPacketID.NAK:
            naks += 1
            self.assertLess(naks, self.MAX_NAKS)

            pid, data = yield from self.in_transaction(data_pid=USBPacketID.DATA1)

        # If this wasn't stalled, ensure we get a ZLP back.
        if pid != USBPacketID.STALL:
            self.assertEqual(data, [])

        # Finally, return our handshake.
        return pid


    def get_descriptor(self, descriptor_type, index=0, length=64):
        """ Performs a GET_DESCRIPTOR request; fetching a USB descriptor.

        Parameters:
            descriptor_type -- The descriptor type number to fetch.
            index           -- The descriptor index to fetch.
            length          -- The requested length to read.
        """

        # The type is stored in the MSB of the value; and the index in the LSB.
        value = descriptor_type << 8 | index
        descriptor = yield from self.control_request_in(0x80,
                USBStandardRequests.GET_DESCRIPTOR, value=value, length=length)

        return descriptor


    def set_address(self, new_address, update_address=True):
        """ Performs a SET_ADDRESS request; setting the device address.

        Parameters:
            new_address -- The address to apply.
        """

        response_pid = yield from self.control_request_out(0,
            USBStandardRequests.SET_ADDRESS, value=new_address)

        if update_address and (response_pid == USBPacketID.DATA1):
            self.address = new_address

        return response_pid


    def set_configuration(self, number):
        """ Performs a SET_CONFIGURATION request; configuring the device.

        Parameters:
            number -- The configuration to select.
        """
        response_pid = yield from self.control_request_out(0,
            USBStandardRequests.SET_CONFIGURATION, value=number)
        return response_pid


    def get_configuration(self):
        """ Performs a GET_CONFIGURATION request; reading the device's configuration. """
        response = yield from self.control_request_in(0x80,
            USBStandardRequests.GET_CONFIGURATION, length=1)
        return response
