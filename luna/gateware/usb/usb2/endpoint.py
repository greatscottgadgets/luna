#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Gateware for working with abstract endpoints. """

import functools
import operator

from amaranth         import Signal, Elaboratable, Module
from amaranth.hdl.ast import Past

from .packet          import DataCRCInterface, InterpacketTimerInterface, TokenDetectorInterface
from .packet          import HandshakeExchangeInterface
from ..stream         import USBInStreamInterface, USBOutStreamInterface
from ...utils.bus     import OneHotMultiplexer


class EndpointInterface:
    """ Interface that connects a USB endpoint module to a USB device.

    Many non-control endpoints won't need to use the latter half of this structure;
    it will be automatically removed by the relevant synthesis tool.

    Attributes
    ----------
    tokenizer: TokenDetectorInterface, to detector
        Interface to our TokenDetector; notifies us of USB tokens.

    rx: USBOutStreamInterface, input stream to endpoint
        Receive interface for this endpoint.
    rx_complete: Signal(), input to endpoint
        Strobe that indicates that the concluding rx-stream was valid (CRC check passed).
    rx_ready_for_response: Signal(), input to endpoint
        Strobe that indicates that we're ready to respond to a complete transmission.
        Indicates that an interpacket delay has passed after an `rx_complete` strobe.
    rx_invalid: Signal(), input to endpoint
        Strobe that indicates that the concluding rx-stream was invalid (CRC check failed).
    rx_pid_toggle: Signal(), input to endpoint
        Value for the data PID toggle; 0 indicates we're receiving a DATA0; 1 indicates Data1.

    tx: USBInStreamInterface, output stream from endpoint
        Transmit interface for this endpoint.
    tx_pid_toggle: Signal(2), output from endpoint
        Value for the data PID toggle; 0 indicates we'll send DATA0; 1 indicates DATA1.
        2 indicates we'll send DATA2, while 3 indicates we'll send DATAM.

    handshakes_in: HandshakeExchangeInterface, input to endpoint
        Carries handshakes detected from the host.
    handshakes_out: HandshakeExchangeInterface, output from endpoint
        Carries handshakes generate by this endpoint.

    speed: Signal(2), input to endpoint
        The device's current operating speed. Should be a USBSpeed enumeration value --
        0 for high, 1 for full, 2 for low.

    active_address: Signal(7), input to endpoint
        Contains the device's current address.
    address_changed: Signal(), output from endpoint.
        Strobe; pulses high when the device's address should be changed.
    new_address: Signal(7), output from endpoint
        When :attr:`address_changed` is high, this field contains the address that should be adopted.

    active_config: Signal(8), input to endpoint
        The configuration number of the active configuration.
    config_changed: Signal(), output from endpoint
        Strobe; pulses high when the device's configuration should be changed.
    new_config: Signal(8)
        When `config_changed` is high, this field contains the configuration that should be applied.

    timer: InterpacketTimerInterface
        Interface to our interpacket timer.
    data_crc: DataCRCInterface
        Control connection for our data-CRC unit.
    """

    def __init__(self):
        self.data_crc              = DataCRCInterface()
        self.tokenizer             = TokenDetectorInterface()
        self.timer                 = InterpacketTimerInterface()

        self.speed                 = Signal(2)

        self.active_address        = Signal(7)
        self.address_changed       = Signal()
        self.new_address           = Signal(7)

        self.active_config         = Signal(8)
        self.config_changed        = Signal()
        self.new_config            = Signal(8)

        self.rx                    = USBOutStreamInterface()
        self.rx_complete           = Signal()
        self.rx_ready_for_response = Signal()
        self.rx_invalid            = Signal()
        self.rx_pid_toggle         = Signal(2)

        self.tx                    = USBInStreamInterface()
        self.tx_pid_toggle         = Signal(2)

        self.handshakes_in         = HandshakeExchangeInterface(is_detector=True)
        self.handshakes_out        = HandshakeExchangeInterface(is_detector=False)
        self.issue_stall           = Signal()


class USBEndpointMultiplexer(Elaboratable):
    """ Multiplexes access to the resources shared between multiple endpoint interfaces.

    Interfaces are added using :attr:`add_interface`.

    Attributes
    ----------

    shared: EndpointInterface
        The post-multiplexer endpoint interface.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.shared = EndpointInterface()

        #
        # Internals
        #
        self._interfaces = []


    def add_interface(self, interface: EndpointInterface):
        """ Adds a EndpointInterface to the multiplexer.

        Arbitration is not performed; it's expected only one endpoint will be
        driving the transmit lines at a time.
        """
        self._interfaces.append(interface)


    def _multiplex_signals(self, m, *, when, multiplex, sub_bus=None):
        """ Helper that creates a simple priority-encoder multiplexer.

        Parmeters
        ---------
        when: str
            The name of the interface signal that indicates that the `multiplex` signals should be
            selected for output. If this signals should be multiplexed, it should be included in `multiplex`.
        multiplex: iterable(str)
            The names of the interface signals to be multiplexed.
        """

        def get_signal(interface, name):
            """ Fetches an interface signal by name / sub_bus. """

            if sub_bus:
                bus = getattr(interface, sub_bus)
                return getattr(bus, name)
            else:
                return  getattr(interface, name)


        # We're building an if-elif tree; so we should start with an If entry.
        conditional = m.If

        for interface in self._interfaces:
            condition = get_signal(interface, when)

            with conditional(condition):

                # Connect up each of our signals.
                for signal_name in multiplex:

                    # Get the actual signals for our input and output...
                    driving_signal = get_signal(interface,   signal_name)
                    target_signal  = get_signal(self.shared, signal_name)

                    # ... and connect them.
                    m.d.comb += target_signal   .eq(driving_signal)

            # After the first element, all other entries should be created with Elif.
            conditional = m.Elif


    def or_join_interface_signals(self, m, signal_for_interface):
        """ Joins together a set of signals on each interface by OR'ing the signals together. """

        # Find the value of all of our pre-mux signals OR'd together...
        all_signals = (signal_for_interface(i) for i in self._interfaces)
        or_value = functools.reduce(operator.__or__, all_signals, 0)

        # ... and tie it to our post-mux signal.
        m.d.comb += signal_for_interface(self.shared).eq(or_value)


    def elaborate(self, platform):
        m = Module()
        shared = self.shared

        #
        # Pass through signals being routed -to- our pre-mux interfaces.
        #
        for interface in self._interfaces:
            m.d.comb += [

                # CRC and timer shared signals interface.
                interface.data_crc.crc           .eq(shared.data_crc.crc),
                interface.timer.tx_allowed       .eq(shared.timer.tx_allowed),
                interface.timer.tx_timeout       .eq(shared.timer.tx_timeout),
                interface.timer.rx_timeout       .eq(shared.timer.rx_timeout),

                # Detectors.
                shared.handshakes_in             .connect(interface.handshakes_in),
                shared.tokenizer                 .connect(interface.tokenizer),

                # Rx interface.
                shared.rx                        .connect(interface.rx),
                interface.rx_complete            .eq(shared.rx_complete),
                interface.rx_ready_for_response  .eq(shared.rx_ready_for_response),
                interface.rx_invalid             .eq(shared.rx_invalid),
                interface.rx_pid_toggle          .eq(shared.rx_pid_toggle),

                # State signals.
                interface.speed                  .eq(shared.speed),
                interface.active_config          .eq(shared.active_config),
                interface.active_address         .eq(shared.active_address)
            ]

        #
        # Multiplex the signals being routed -from- our pre-mux interface.
        #
        self._multiplex_signals(m,
            when='address_changed',
            multiplex=['address_changed', 'new_address']
        )
        self._multiplex_signals(m,
            when='config_changed',
            multiplex=['config_changed', 'new_config']
        )

        # Connect up our transmit interface.
        m.submodules.tx_mux = tx_mux = OneHotMultiplexer(
            interface_type=USBInStreamInterface,
            mux_signals=('payload',),
            or_signals=('valid', 'first', 'last'),
            pass_signals=('ready',)
        )
        tx_mux.add_interfaces(i.tx for i in self._interfaces)
        m.d.comb += self.shared.tx.stream_eq(tx_mux.output)

        # OR together all of our handshake-generation requests...
        self.or_join_interface_signals(m, lambda interface : interface.handshakes_out.ack)
        self.or_join_interface_signals(m, lambda interface : interface.handshakes_out.nak)
        self.or_join_interface_signals(m, lambda interface : interface.handshakes_out.stall)

        # ... our CRC start signals...
        self.or_join_interface_signals(m, lambda interface : interface.data_crc.start)

        # ... and our timer start signals.
        self.or_join_interface_signals(m, lambda interface : interface.timer.start)

        # Finally, connect up our transmit PID select.
        conditional = m.If

        # We'll connect our PID toggle to whichever interface has a valid transmission going.
        for interface in self._interfaces:
            with conditional(interface.tx.valid | Past(interface.tx.valid, domain="usb")):
                m.d.comb += shared.tx_pid_toggle.eq(interface.tx_pid_toggle)

            conditional = m.Elif

        return m
