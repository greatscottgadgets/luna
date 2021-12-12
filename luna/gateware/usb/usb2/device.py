#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
"""
Contains the organizing hardware used to add USB Device functionality
to your own designs; including the core :class:`USBDevice` class.
"""

import logging
import unittest

from luna                      import configure_default_logging

from amaranth                  import Signal, Module, Elaboratable, Const
from usb_protocol.types        import DescriptorTypes
from usb_protocol.emitters     import DeviceDescriptorCollection

from ...interface.ulpi         import UTMITranslator
from ...interface.utmi         import UTMIInterfaceMultiplexer
from ...interface.gateware_phy import GatewarePHY

from .                         import USBSpeed, USBPacketID
from .packet                   import USBTokenDetector, USBHandshakeGenerator, USBDataPacketCRC
from .packet                   import USBInterpacketTimer, USBDataPacketGenerator, USBHandshakeDetector
from .packet                   import USBDataPacketReceiver
from .reset                    import USBResetSequencer

from .endpoint                 import USBEndpointMultiplexer
from .control                  import USBControlEndpoint

from ...test                   import usb_domain_test_case
from ...test.usb2              import USBDeviceTest


class USBDevice(Elaboratable):
    """ Core gateware common to all LUNA USB2 devices.

    The ``USBDevice`` module contains the low-level communications hardware necessary to implement a USB device;
    including hardware for maintaining device state, detecting events, reading data from the host, and generating
    responses.

    This class can be instantiated directly, and used to build a USB device,
    or can be subclassed to create custom device types.

    To configure a ``USBDevice`` from a CPU or other wishbone master, see :class:`USBDeviceController`;
    which can easily be attached using its `attach` method.


    Parameters
    ----------

    bus: [UTMI interface, ULPI Interface]
        The UTMI or ULPI PHY connection to be used for communications.

    handle_clocking: bool, Optional
        True iff we should attempt to connect up the `usb` clock domain to the PHY
        automatically based on the clk signals's I/O direction. This option may not work
        for non-simple connections; in which case you will need to connect the clock signal
        yourself.


    Attributes
    ----------

    connect: Signal(), input
        Held high to keep the current USB device connected; or held low to disconnect.
    low_speed_only: Signal(), input
        If high, the device will operate at low speed.
    full_speed_only: Signal(), input
        If high, the device will be prohibited from operating at high speed.

    frame_number: Signal(11), output
        The current USB frame number.
    microframe_number: Signal(3), output
        The current USB microframe number. Always 0 on non-HS connections.
    sof_detected: Signal(), output
        Pulses for one cycle each time a SOF is detected; and thus our frame number has changed.
    new_frame: Signal(), output
        Strobe that indicates a new frame (not microframe) is detected.

    reset_detected: Signal(), output
        Asserted when the USB device receives a bus reset.

    # State signals.
    suspended: Signal(), output
        High when the device is in USB suspend. This can be (and by the spec must be) used to trigger
        the device to enter lower-power states.

    tx_activity_led: Signal(), output
        Signal that can be used to drive an activity LED for TX.
    rx_activity_led: Signal(), output
        Signal that can be used to drive an activity LED for RX.

    """

    def __init__(self, *, bus, handle_clocking=True):
        """
        Parameters:
        """

        # If this looks more like a ULPI bus than a UTMI bus, translate it.
        if hasattr(bus, 'dir'):
            self.utmi       = UTMITranslator(ulpi=bus, handle_clocking=handle_clocking)
            self.bus_busy   = self.utmi.busy
            self.translator = self.utmi
            self.always_fs  = False
            self.data_clock = 60e6

        # If this looks more like raw I/O connections than a UTMI bus, create a pure-gatware
        # PHY to drive the raw I/O signals.
        elif hasattr(bus, 'd_n'):
            self.utmi       = GatewarePHY(io=bus)
            self.bus_busy   = Const(0)
            self.translator = self.utmi
            self.always_fs  = True
            self.data_clock = 12e6

        # Otherwise, use it directly.
        # Note that since a true UTMI interface has separate Tx/Rx/control
        # interfaces, we don't need to care about bus 'busyness'; so we'll
        # set it to a const zero.
        else:
            self.utmi       = bus
            self.bus_busy   = Const(0)
            self.translator = None
            self.always_fs  = True
            self.data_clock = 12e6

        #
        # I/O port
        #
        self.connect           = Signal()
        self.low_speed_only    = Signal()
        self.full_speed_only   = Signal()

        self.frame_number      = Signal(11)
        self.microframe_number = Signal(3)
        self.sof_detected      = Signal()
        self.new_frame         = Signal()
        self.reset_detected    = Signal()

        self.speed             = Signal(2)
        self.suspended         = Signal()
        self.tx_activity_led   = Signal()
        self.rx_activity_led   = Signal()

        #
        # Internals.
        #
        self._endpoints = []


    def add_endpoint(self, endpoint):
        """ Adds an endpoint interface to the device.

        Parameters
        ----------
        endpoint: Elaborateable
            The endpoint interface to be added. Can be any piece of gateware with a
            :class:`EndpointInterface` attribute called ``interface``.
        """
        self._endpoints.append(endpoint)


    def add_control_endpoint(self):
        """ Adds a basic control endpoint to the device.

        Does not add any request handlers. If you want standard request handlers;
        :attr:`add_standard_control_endpoint` automatically adds standard request handlers.

        Returns
        -------
        Returns the endpoint object for the control endpoint.
        """
        control_endpoint = USBControlEndpoint(utmi=self.utmi)
        self.add_endpoint(control_endpoint)

        return control_endpoint


    def add_standard_control_endpoint(self, descriptors: DeviceDescriptorCollection, **kwargs):
        """ Adds a control endpoint with standard request handlers to the device.

        Parameters will be passed on to StandardRequestHandler.

        Return value
        ------------
        The endpoint object created.
        """

        # Create our endpoint, and add standard descriptors to it.
        control_endpoint = USBControlEndpoint(utmi=self.utmi)
        control_endpoint.add_standard_request_handlers(descriptors, **kwargs)
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


        #
        # Internal interconnections.
        #

        # Create our reset sequencer, which will be in charge of detecting USB port resets,
        # detecting high-speed hosts, and communicating that we are a high speed device.
        m.submodules.reset_sequencer = reset_sequencer = USBResetSequencer()

        m.d.comb += [
            reset_sequencer.bus_busy        .eq(self.bus_busy),

            reset_sequencer.vbus_connected  .eq(~self.utmi.session_end),
            reset_sequencer.line_state      .eq(self.utmi.line_state),
        ]


        # Create our internal packet components:
        # - A token detector, which will identify and parse the tokens that start transactions.
        # - A data transmitter, which will transmit provided data streams.
        # - A data receiver, which will receive data from UTMI and convert it into streams.
        # - A handshake generator, which will assist in generating response packets.
        # - A handshake detector, which detects handshakes generated by the host.
        # - A data CRC16 handler, which will compute data packet CRCs.
        # - An interpacket delay timer, which will enforce interpacket delays.
        m.submodules.token_detector      = token_detector      = \
            USBTokenDetector(utmi=self.utmi, domain_clock=self.data_clock, fs_only=self.always_fs)
        m.submodules.transmitter         = transmitter         = USBDataPacketGenerator()
        m.submodules.receiver            = receiver            = USBDataPacketReceiver(utmi=self.utmi)
        m.submodules.handshake_generator = handshake_generator = USBHandshakeGenerator()
        m.submodules.handshake_detector  = handshake_detector  = USBHandshakeDetector(utmi=self.utmi)
        m.submodules.data_crc            = data_crc            = USBDataPacketCRC()
        m.submodules.timer               = timer               = \
            USBInterpacketTimer(domain_clock=self.data_clock, fs_only=self.always_fs)

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
            token_detector.speed    .eq(self.speed),
            timer.speed             .eq(self.speed)
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
            endpoint_collection.speed                  .eq(self.speed),
            endpoint_collection.active_config          .eq(configuration),
            endpoint_collection.active_address         .eq(address),

            # Receive interface.
            receiver.stream                            .connect(endpoint_collection.rx),
            endpoint_collection.rx_complete            .eq(receiver.packet_complete),
            endpoint_collection.rx_invalid             .eq(receiver.crc_mismatch),
            endpoint_collection.rx_ready_for_response  .eq(receiver.ready_for_response),
            endpoint_collection.rx_pid_toggle          .eq(receiver.active_pid[3]),

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
        tx_multiplexer.add_input(reset_sequencer.tx)
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


        # Device operating state controls.
        m.d.comb += [
            # Disable our host-mode pulldowns; as we're a device.
            self.utmi.dm_pulldown            .eq(0),
            self.utmi.dp_pulldown            .eq(0),

            # Let our reset sequencer set our USB mode and speed.
            reset_sequencer.low_speed_only   .eq(self.low_speed_only & ~self.always_fs),
            reset_sequencer.full_speed_only  .eq(self.full_speed_only | self.always_fs),
            self.utmi.op_mode                .eq(reset_sequencer.operating_mode),
            self.utmi.xcvr_select            .eq(reset_sequencer.current_speed),
            self.utmi.term_select            .eq(reset_sequencer.termination_select & self.connect),
        ]

        #
        # Frame/microframe state.
        #

        # Handle each new SOF token as we receive them.
        with m.If(token_detector.interface.new_frame):

            # Update our knowledge of the current frame number.
            m.d.usb += self.frame_number.eq(token_detector.interface.frame)

            # Check if we're receiving a new 1ms frame -- which occurs when the new SOF's
            # frame number is different from the previous one's. This will always be the case
            # on full speed links; and will be the case 1/8th of the time on High Speed links.
            m.d.comb += self.new_frame.eq(token_detector.interface.frame != self.frame_number)

            # If this is a new frame, our microframe count should be zero.
            with m.If(self.new_frame):
                m.d.usb += self.microframe_number.eq(0)

            # Otherwise, this SOF indicates a new _microframe_ [USB 2.0: 8.4.3.1].
            with m.Else():
                m.d.usb += self.microframe_number.eq(self.microframe_number + 1)


        #
        # Device-state outputs.
        #
        m.d.comb += [
            self.speed            .eq(reset_sequencer.current_speed),
            self.suspended        .eq(reset_sequencer.suspended),

            self.sof_detected     .eq(token_detector.interface.new_frame),
            self.reset_detected   .eq(reset_sequencer.bus_reset),

            self.tx_activity_led  .eq(tx_multiplexer.output.valid),
            self.rx_activity_led  .eq(self.utmi.rx_valid)
        ]

        return m


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


#
# Section that requires our CPU framework.
# We'll very deliberately section that off, so it
#
try:

    from ...soc.peripheral import Peripheral

    class USBDeviceController(Peripheral, Elaboratable):
        """ SoC controller for a USBDevice.

        Breaks our USBDevice control and status signals out into registers so a CPU / Wishbone master
        can control our USB device.

        The attributes below are intended to connect to a USBDevice. Typically, they'd be created by
        using the .controller() method on a USBDevice object, which will automatically connect all
        relevant signals.

        Attributes
        ----------

        connect: Signal(), output
            High when the USBDevice should be allowed to connect to a host.

        """

        def __init__(self):
            super().__init__()

            #
            # I/O port
            #
            self.connect   = Signal(reset=1)
            self.bus_reset = Signal()


            #
            # Registers.
            #

            regs = self.csr_bank()
            self._connect = regs.csr(1, "rw", desc="""
                Set this bit to '1' to allow the associated USB device to connect to a host.
            """)

            self._speed = regs.csr(2, "r", desc="""
                Indicates the current speed of the USB device. 0 indicates High; 1 => Full,
                2 => Low, and 3 => SuperSpeed (incl SuperSpeed+).
            """)

            self._reset_irq = self.event(name="reset", desc="""
                Interrupt that occurs when a USB bus reset is received.
            """)

            # Wishbone connection.
            self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
            self.bus        = self._bridge.bus
            self.irq        = self._bridge.irq


        def attach(self, device: USBDevice):
            """ Returns a list of statements necessary to connect this to a USB controller.

            The returned values makes all of the connections necessary to provide control and fetch status
            from the relevant USB device. These can be made either combinationally or synchronously, but
            combinational is recommended; as these signals are typically fed from a register anyway.

            Parameters
            ----------
            device: USBDevice
                The :class:`USBDevice` object to be controlled.
            """
            return [
                device.connect      .eq(self.connect),
                self.bus_reset      .eq(device.reset_detected),
                self._speed.r_data  .eq(device.speed)
            ]


        def elaborate(self, platform):
            m = Module()
            m.submodules.bridge = self._bridge

            # Core connection register.
            m.d.comb += self.connect.eq(self._connect.r_data)
            with m.If(self._connect.w_stb):
                m.d.usb += self._connect.r_data.eq(self._connect.w_data)

            # Reset-detection event.
            m.d.comb += self._reset_irq.stb.eq(self.bus_reset)

            return m


except ImportError as e:
    # Since this exception happens so early, top_level_cli won't have set up logging yet,
    # so call the setup here to avoid getting stuck with Python's default config.
    configure_default_logging()

    logging.warning("SoC framework components could not be imported; some functionality will be unavailable.")
    logging.warning(e)



if __name__ == "__main__":
    unittest.main()
