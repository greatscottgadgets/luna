#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- exposes packet interfaces. """

import unittest

from nmigen            import Signal, Module, Elaboratable, Memory, Cat, Const, Record
from ...test           import LunaGatewareTestCase, ulpi_domain_test_case, sync_test_case

from .packet           import USBTokenDetector, USBHandshakeGenerator
from .control          import USBControlEndpoint
from ...interface.ulpi import UTMITranslator


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
        self.connect      = Signal()

        self.frame_number = Signal(11)
        self.sof_detected = Signal()

        # Debug I/O.
        self.last_request = Signal(8)
        self.new_packet   = Signal()


    def elaborate(self, platform):
        m = Module()

        # If we have a bus translator, include it in our submodules.
        if self.translator:
            m.submodules.translator = self.translator


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

        # Create our internal packet components:
        # - A token detector, which will identify and parse the tokens that start transactions.
        # - A handshake generator, which will assist in generating response packets.
        m.submodules.token_detector      = token_detector      = USBTokenDetector(utmi=self.utmi)
        m.submodules.handshake_generator = handshake_generator = USBHandshakeGenerator()

        # TODO: abstract this into an add-control-endpoint request
        m.submodules.control_ep = control_ep = USBControlEndpoint(utmi=self.utmi, tokenizer=token_detector)

        # TODO: implement bus-access logic
        m.d.comb += [
            self.utmi.tx_data              .eq(handshake_generator.tx_data),
            self.utmi.tx_valid             .eq(handshake_generator.tx_valid),

            handshake_generator.tx_ready   .eq(self.utmi.tx_ready),
            handshake_generator.issue_ack  .eq(control_ep.issue_ack)

        ]

        # Pass through our global device-state signals.
        m.d.comb += [
            self.sof_detected  .eq(token_detector.new_frame),
            self.frame_number  .eq(token_detector.frame),

            # Debug only.
            self.last_request  .eq(control_ep.last_request),
            self.new_packet    .eq(control_ep.new_packet)
        ]

        return m


if __name__ == "__main__":
    unittest.main()
