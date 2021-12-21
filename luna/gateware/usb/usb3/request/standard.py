#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Standard, full-gateware control request handlers. """

import unittest

from amaranth                 import *

from usb_protocol.types       import USBStandardRequests, USBRequestType
from usb_protocol.emitters    import DeviceDescriptorCollection

from ..application.request    import SuperSpeedRequestHandlerInterface
from ..application.descriptor import GetDescriptorHandler

from ...stream                import SuperSpeedStreamInterface
from ....utils                import falling_edge_detected


class StandardRequestHandler(Elaboratable):
    """ Pure-gateware USB3 setup request handler. Implements the standard requests required for enumeration. """

    def __init__(self, descriptors: DeviceDescriptorCollection):
        self.descriptors = descriptors

        #
        # I/O port
        #
        self.interface = SuperSpeedRequestHandlerInterface()



    def handle_register_write_request(self, m, new_value_signal, write_strobe, stall_condition=0):
        """ Fills in the current state with a request handler meant to set a register.

        Parameters
        ----------
        new_value_signal: Signal of any size
            The signal to receive the new value to be applied to the relevant register.
        write_strobe: Signal()
            The signal which will be pulsed when new_value_signal contains a update.
        stall_condition:
            If provided, if this condition is true, the request will be STALL'd instead of acknowledged.
            """

        # Provide an response to the STATUS stage.
        with m.If(self.interface.status_requested):

            # If our stall condition is met, stall; otherwise, send an ACK.
            with m.If(stall_condition):
                m.d.comb += self.interface.handshakes_out.send_stall.eq(1)
            with m.Else():
                m.d.comb += self.interface.handshakes_out.send_ack.eq(1)

            m.d.comb += [
                write_strobe      .eq(1),
                new_value_signal  .eq(self.interface.setup.value[0:7])
            ]

            # ... and then return to idle.
            m.next = 'IDLE'


    def handle_simple_data_request(self, m, data, *, length=1):
        """ Fills in a given current state with a request that returns a given short piece of data.

        For e.g. GET_CONFIGURATION and GET_STATUS requests. The relevant data must fit within a word.

        Parameters
        ----------
        tx_stream: StreamInterface
            The transmit stream to drive.
        data: Amaranth value, or equivalent, up to 32b
            The data to be transmitted.
        valid_mask: Amaranth value, or equivalent, up to 4b
            The valid mask for the data to be transmitted. Should be 0b0001, 0b0011, 0b0111, or 0b1111.
        """

        # Create a simple mapping of our valid bits to lengths.
        # Slightly clearer than the arithmetic version. :)
        valid_bits_for_length = [0b0000, 0b0001, 0b0011, 0b0111, 0b1111]

        # Provide our output stream with our simple word.
        tx_valid = Signal(4)
        m.d.comb += [
            self.interface.tx.valid   .eq(tx_valid),

            self.interface.tx.first   .eq(1),
            self.interface.tx.last    .eq(1),

            self.interface.tx.data    .eq(data),
            self.interface.tx_length  .eq(length)
        ]

        # When data is requested, start sending.
        with m.If(self.interface.data_requested):
            m.d.ss += tx_valid.eq(valid_bits_for_length[length])

        # Once our transmitter has accepted data, stop sending.
        with m.If(self.interface.tx.ready):
            m.d.ss += tx_valid.eq(0)

        # ACK our status stage, when appropriate.
        with m.If(self.interface.status_requested):
            m.d.comb += self.interface.handshakes_out.send_ack.eq(1)
            m.next = 'IDLE'



    def elaborate(self, platform):
        m = Module()
        interface = self.interface

        # Create convenience aliases for our interface components.
        setup               = interface.setup
        handshake_generator = interface.handshakes_out

        # For all of our handshakes, set our next-sequence-number to one; as we never receive
        # packets, and ACKs should be seq=1.
        m.d.comb += handshake_generator.next_sequence.eq(1)


        #
        # Submodules
        #

        # Handler for Get Descriptor requests; responds with our various fixed descriptors.
        m.submodules.get_descriptor = get_descriptor_handler = GetDescriptorHandler(self.descriptors,
            usb_domain  = "ss",
            stream_type = SuperSpeedStreamInterface
        )
        m.d.comb += [
            get_descriptor_handler.value  .eq(setup.value),
            get_descriptor_handler.length .eq(setup.length),
        ]


        ##
        ## Handlers.
        ##
        with m.If(setup.type == USBRequestType.STANDARD):
            with m.FSM(domain="ss"):

                # IDLE -- not handling any active request
                with m.State('IDLE'):

                    # If we've received a new setup packet, handle it.
                    with m.If(setup.received):

                        # Select which standard packet we're going to handler.
                        with m.Switch(setup.request):

                            with m.Case(USBStandardRequests.GET_STATUS):
                                m.next = 'GET_STATUS'
                            with m.Case(USBStandardRequests.SET_ADDRESS):
                                m.next = 'SET_ADDRESS'
                            with m.Case(USBStandardRequests.SET_CONFIGURATION):
                                m.next = 'SET_CONFIGURATION'
                            with m.Case(USBStandardRequests.GET_DESCRIPTOR):
                                m.next = 'GET_DESCRIPTOR'
                            with m.Case(USBStandardRequests.GET_CONFIGURATION):
                                m.next = 'GET_CONFIGURATION'
                            with m.Case(USBStandardRequests.SET_ISOCH_DELAY):
                                m.next = 'SET_ISOCH_DELAY'
                            with m.Case(USBStandardRequests.SET_SEL):
                                m.next = 'SET_SEL'
                            with m.Case():
                                m.next = 'UNHANDLED'


                # GET_STATUS -- Fetch the device's status.
                # For now, we'll always return '0'.
                with m.State('GET_STATUS'):
                    # TODO: handle reporting endpoint stall status
                    # TODO: copy the remote wakeup and bus-powered attributes from bmAttributes of the relevant descriptor?
                    self.handle_simple_data_request(m, 0, length=2)


                # SET_ADDRESS -- The host is trying to assign us an address.
                with m.State('SET_ADDRESS'):
                    self.handle_register_write_request(m, interface.new_address, interface.address_changed)


                # SET_CONFIGURATION -- The host is trying to select an active configuration.
                with m.State('SET_CONFIGURATION'):
                    # TODO: stall if we don't have a relevant configuration
                    self.handle_register_write_request(m, interface.new_config, interface.config_changed)


                # GET_DESCRIPTOR -- The host is asking for a USB descriptor -- for us to "self describe".
                with m.State('GET_DESCRIPTOR'):
                    m.d.comb += [
                        interface.tx                    .stream_eq(get_descriptor_handler.tx),
                        interface.tx_length             .eq(get_descriptor_handler.tx_length),

                        handshake_generator.send_stall  .eq(get_descriptor_handler.stall)
                    ]

                    # Respond to our data stage with a descriptor...
                    with m.If(interface.data_requested):
                        m.d.comb += get_descriptor_handler.start  .eq(1),

                    # ... and ACK our status stage.
                    with m.If(interface.status_requested):
                        m.d.comb += handshake_generator.send_ack.eq(1)
                        m.next = 'IDLE'


                # GET_CONFIGURATION -- The host is asking for the active configuration number.
                with m.State('GET_CONFIGURATION'):
                    self.handle_simple_data_request(m, interface.active_config)


                # SET_ISOCH_DELAY -- The host is trying to inform us of our isochronous delay.
                with m.State('SET_ISOCH_DELAY'):
                    # TODO: store this data aside once we support ISOCH
                    #self.handle_register_write_request(m, interface.new_config, interface.config_changed)

                    # ACK our status stage, when appropriate.
                    with m.If(self.interface.status_requested):
                        m.d.comb += self.interface.handshakes_out.send_ack.eq(1)
                        m.next = 'IDLE'


                # SET_SEL -- set our System Exit Latencies
                with m.State('SET_SEL'):
                    # TODO: use the actual latencies once we support USB3 power states

                    # ACK the data that's coming in, once we get it; but ignore it for now
                    data_received = falling_edge_detected(m, interface.rx.valid, domain="ss")
                    with m.If(data_received):
                        m.d.comb += self.interface.handshakes_out.send_ack.eq(1)


                    # ACK our status stage, when appropriate.
                    with m.If(self.interface.status_requested):
                        m.d.comb += self.interface.handshakes_out.send_ack.eq(1)
                        m.next = 'IDLE'


                # UNHANDLED -- we've received a request we're not prepared to handle
                with m.State('UNHANDLED'):

                    # When we next have an opportunity to stall, do so, and then return to idle.
                    data_received = falling_edge_detected(m, interface.rx.valid, domain="ss")
                    with m.If(interface.data_requested | interface.status_requested | data_received):
                        m.d.comb += handshake_generator.send_stall.eq(1)
                        m.next = 'IDLE'

        return m


if __name__ == "__main__":
    unittest.main(warnings="ignore")

