#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- exposes packet interfaces. """

import unittest

from nmigen                 import Signal, Module, Elaboratable
from usb_protocol.types     import DescriptorTypes
from usb_protocol.emitters  import DeviceDescriptorCollection


from ...interface.ulpi      import UTMITranslator
from ...interface.utmi      import UTMIInterfaceMultiplexer

from .                      import USBSpeed, USBPacketID
from .packet                import USBTokenDetector, USBHandshakeGenerator, USBDataPacketCRC
from .packet                import USBInterpacketTimer, USBDataPacketGenerator, USBHandshakeDetector
from .packet                import USBDataPacketReceiver
from .reset                 import USBResetSequencer

from .endpoint              import USBEndpointMultiplexer
from .control               import USBControlEndpoint

from ...test                import usb_domain_test_case
from ...test.usb2           import USBDeviceTest


class USBDevice(Elaboratable):
    """ Class representing an abstract USB device.

    Can be instantiated directly, and used to build a USB device,
    or can be subclassed to create custom device types.

    The I/O for this device is generically created dynamically; but
    a few signals are exposed:

        I: connect          -- Held high to keep the current USB device connected; or
                               held low to disconnect.

        O: frame_number[11] -- The current USB frame number.
        O: sof_detected     -- Pulses for one cycle each time a SOF is detected; and thus our
                               frame number has changed.

        # State signals.
        O: tx_activity_led  -- Signal that can be used to drive an activity LED for TX.
        O: rx_activity_led  -- Signal that can be used to drive an activity LED for RX.
    """

    def __init__(self, *, bus):
        """
        Parameters:
            bus -- The UTMI or ULPI PHY connection to be used for communications.
        """

        # If this looks more like a ULPI bus than a UTMI bus, translate it.
        if not hasattr(bus, 'rx_valid'):
            self.utmi       = UTMITranslator(ulpi=bus)
            self.translator = self.utmi

        # Otherwise, use it directly.
        else:
            self.utmi       = bus
            self.translator = None

        #
        # I/O port
        #
        self.connect         = Signal()

        self.frame_number    = Signal(11)
        self.sof_detected    = Signal()

        self.tx_activity_led = Signal()
        self.rx_activity_led = Signal()

        #
        # Internals.
        #
        self._endpoints = []


    def add_endpoint(self, endpoint):
        """ Adds an endpoint to the device. """
        self._endpoints.append(endpoint)


    def add_control_endpoint(self):
        """ Adds a basic control endpoint to the device.

        Does not add any request handlers. If you want standard request handlers;
        `add_standard_control_endpoint` automatically adds standard request handlers.

        Returns the endpoint object.
        """
        control_endpoint = USBControlEndpoint(utmi=self.utmi)
        self.add_endpoint(control_endpoint)


    def add_standard_control_endpoint(self, descriptors: DeviceDescriptorCollection):
        """ Adds a control endpoint with standard request handlers to the device.

        Parameters:
            descriptors -- The descriptors to use for this device.

        Returns the endpoint object created.
        """

        # Create our endpoint, and add standard descriptors to it.
        control_endpoint = USBControlEndpoint(utmi=self.utmi)
        control_endpoint.add_standard_request_handlers(descriptors)
        self.add_endpoint(control_endpoint)

        return control_endpoint


    def elaborate(self, platform):
        m = Module()

        # If we have a bus translator, include it in our submodules.
        if self.translator:
            m.submodules.translator = self.translator


        #
        # Internal device state.
        #

        # Stores the device's current address. Used to identify which packets are for us.
        address       = Signal(7, reset=0)

        # Stores the device's current configuration. Defaults to unconfigured.
        configuration = Signal(8, reset=0)

        # Stores the device's current speed (a USBSpeed value).
        speed         = Signal(2, reset=USBSpeed.FULL)


        #
        # Internal interconnections.
        #

        # Device operating state controls.
        m.d.comb += [

            # Disable our host-mode pulldowns; as we're a device.
            self.utmi.dm_pulldown  .eq(0),

            # Connect our termination whenever the device is connected.
            # TODO: support high-speed termination disconnect.
            self.utmi.term_select  .eq(self.connect),

            # For now, fix us into FS mode.
            self.utmi.op_mode      .eq(0b00),
            self.utmi.xcvr_select  .eq(0b01)
        ]

        # Create our reset sequencer, which will be in charge of detecting USB port resets,
        # detecting high-speed hosts, and communicating that we are a high speed device.
        m.submodules.reset_sequencer = reset_sequencer = USBResetSequencer()

        m.d.comb += [
            reset_sequencer.speed       .eq(speed),
            reset_sequencer.line_state  .eq(self.utmi.line_state)
        ]


        # Create our internal packet components:
        # - A token detector, which will identify and parse the tokens that start transactions.
        # - A data transmitter, which will transmit provided data streams.
        # - A data receiver, which will receive data from UTMI and convert it into streams.
        # - A handshake generator, which will assist in generating response packets.
        # - A handshake detector, which detects handshakes generated by the host.
        # - A data CRC16 handler, which will compute data packet CRCs.
        # - An interpacket delay timer, which will enforce interpacket delays.
        m.submodules.token_detector      = token_detector      = USBTokenDetector(utmi=self.utmi)
        m.submodules.transmitter         = transmitter         = USBDataPacketGenerator()
        m.submodules.receiver            = receiver            = USBDataPacketReceiver(utmi=self.utmi)
        m.submodules.handshake_generator = handshake_generator = USBHandshakeGenerator()
        m.submodules.handshake_detector  = handshake_detector  = USBHandshakeDetector(utmi=self.utmi)
        m.submodules.data_crc            = data_crc            = USBDataPacketCRC()
        m.submodules.timer               = timer               = USBInterpacketTimer()

        # Connect our transmitter/receiver to our CRC generator.
        data_crc.add_interface(transmitter.crc)
        data_crc.add_interface(receiver.data_crc)

        # Connect our receiver to our timer.
        timer.add_interface(receiver.timer)

        m.d.comb += [
            # Ensure our token detector only responds to tokens addressed to us.
            token_detector.address  .eq(address),

            # Hook up our data_crc to our receive inputs.
            data_crc.rx_data        .eq(self.utmi.rx_data),
            data_crc.rx_valid       .eq(self.utmi.rx_valid),

            # Connect our state signals to our subordinate components.
            token_detector.speed    .eq(speed),
            timer.speed             .eq(speed)
        ]

        #
        # Endpoint connections.
        #

        # Create our endpoint multiplexer...
        m.submodules.endpoint_mux = endpoint_mux = USBEndpointMultiplexer()
        endpoint_collection = endpoint_mux.shared

        # Connect our timer and CRC interfaces.
        timer.add_interface(endpoint_collection.timer)
        data_crc.add_interface(endpoint_collection.data_crc)

        m.d.comb += [
            # Low-level hardware interface.
            token_detector.interface                   .connect(endpoint_collection.tokenizer),
            handshake_detector.detected                .connect(endpoint_collection.handshakes_in),

            # Device state.
            endpoint_collection.speed                  .eq(speed),
            endpoint_collection.active_config          .eq(configuration),

            # Receive interface.
            receiver.stream                            .connect(endpoint_collection.rx),
            endpoint_collection.rx_complete            .eq(receiver.packet_complete),
            endpoint_collection.rx_invalid             .eq(receiver.crc_mismatch),
            endpoint_collection.rx_ready_for_response  .eq(receiver.ready_for_response),

            # Transmit interface.
            endpoint_collection.tx                     .attach(transmitter.stream),
            handshake_generator.issue_ack              .eq(endpoint_collection.handshakes_out.ack),
            handshake_generator.issue_nak              .eq(endpoint_collection.handshakes_out.nak),
            handshake_generator.issue_stall            .eq(endpoint_collection.handshakes_out.stall),
            transmitter.data_pid                       .eq(endpoint_collection.tx_pid_toggle),
        ]

        # If an endpoint wants to update our address or configuration, accept the update.
        with m.If(endpoint_collection.address_changed):
            m.d.usb += address.eq(endpoint_collection.new_address)
        with m.If(endpoint_collection.config_changed):
            m.d.usb += configuration.eq(endpoint_collection.new_config)


        # Finally, add each of our endpoints to this module and our multiplexer.
        for endpoint in self._endpoints:

            # Create a display name for the endpoint...
            name = endpoint.__class__.__name__
            if hasattr(m.submodules, name):
                name = f"{name}_{id(endpoint)}"

            # ... and add it, both as a submodule and to our multiplexer.
            endpoint_mux.add_interface(endpoint.interface)
            m.submodules[name] = endpoint


        #
        # Transmitter multiplexing.
        #

        # Create a multiplexer that will arbitrate access to the transmit lines.
        m.submodules.tx_multiplexer = tx_multiplexer = UTMIInterfaceMultiplexer()

        # Connect each of our transmitters.
        tx_multiplexer.add_input(transmitter.tx)
        tx_multiplexer.add_input(handshake_generator.tx)

        m.d.comb += [
            # Connect our transmit multiplexer to the actual UTMI bus.
            tx_multiplexer.output  .attach(self.utmi),

            # Connect up the transmit CRC interface to our UTMI bus.
            data_crc.tx_valid      .eq(tx_multiplexer.output.valid & self.utmi.tx_ready),
            data_crc.tx_data       .eq(tx_multiplexer.output.data),
        ]


        #
        # Device-state management.
        #

        # On a bus reset, clear our address and configuration.
        with m.If(reset_sequencer.bus_reset):
            m.d.usb += [
                address        .eq(0),
                configuration  .eq(0),
            ]


        #
        # Device-state outputs.
        #

        m.d.comb += [
            self.sof_detected  .eq(token_detector.interface.new_frame),
            self.frame_number  .eq(token_detector.interface.frame),

            self.tx_activity_led  .eq(tx_multiplexer.output.valid)
        ]

        return m


class FullDeviceTest(USBDeviceTest):
    FRAGMENT_UNDER_TEST = USBDevice

    def traces_of_interest(self):
        return (
            self.utmi.tx_data,
            self.utmi.tx_valid,
            self.utmi.rx_data,
            self.utmi.rx_valid,
        )

    def initialize_signals(self):

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


if __name__ == "__main__":
    unittest.main()
