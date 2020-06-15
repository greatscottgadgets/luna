#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Standard, full-gateware control request handlers. """

import unittest

from nmigen                 import Module, Elaboratable, Cat
from usb_protocol.types     import USBStandardRequests, USBRequestType
from usb_protocol.emitters  import DeviceDescriptorCollection


from ..usb2.request         import RequestHandlerInterface, USBRequestHandler
from ..usb2.descriptor      import GetDescriptorHandler
from ..stream               import USBInStreamInterface
from ...stream.generator    import StreamSerializer


class StandardRequestHandler(USBRequestHandler):
    """ Pure-gateware USB setup request handler. Implements the standard requests required for enumeration. """

    def __init__(self, descriptors: DeviceDescriptorCollection):
        """
        Parameters:
            descriptors    -- The DeviceDescriptorCollection that contains our descriptors.
        """
        self.descriptors = descriptors
        super().__init__()


    def handle_register_write_request(self, m, new_value_signal, write_strobe, stall_condition=0):
        """ Fills in the current state with a request handler meant to set a register.

        Parameters:
            new_value_signal -- The signal to receive the new value to be applied to the relevant register.
            write_strobe     -- The signal which will be pulsed when new_value_signal contains a update.
            stall_condition  -- If provided, if this condition is true, the request will be STALL'd instead
                                of acknowledged.
            """

        # Provide an response to the STATUS stage.
        with m.If(self.interface.status_requested):

            # If our stall condition is met, stall; otherwise, send a ZLP [USB 8.5.3].
            with m.If(stall_condition):
                m.d.comb += self.interface.handshakes_out.stall.eq(1)
            with m.Else():
                m.d.comb += self.send_zlp()

        # Accept the relevant value after the packet is ACK'd...
        with m.If(self.interface.handshakes_in.ack):
            m.d.comb += [
                write_strobe      .eq(1),
                new_value_signal  .eq(self.interface.setup.value[0:7])
            ]

            # ... and then return to idle.
            m.next = 'IDLE'


    def handle_simple_data_request(self, m, transmitter, data, length=1):
        """ Fills in a given current state with a request that returns a given piece of data.

        For e.g. GET_CONFIGURATION and GET_STATUS requests.

        Parameters:
            transmitter -- The transmitter module we're working with.
            data        -- The data to be returned.
        """

        # Connect our transmitter up to the output stream...
        m.d.comb += [
            transmitter.stream          .attach(self.interface.tx),
            Cat(transmitter.data[0:1])  .eq(data),
            transmitter.max_length      .eq(length)
        ]

        # ... trigger it to respond when data's requested...
        with m.If(self.interface.data_requested):
            m.d.comb += transmitter.start.eq(1)

        # ... and ACK our status stage.
        with m.If(self.interface.status_requested):
            m.d.comb += self.interface.handshakes_out.ack.eq(1)
            m.next = 'IDLE'



    def elaborate(self, platform):
        m = Module()
        interface = self.interface

        # Create convenience aliases for our interface components.
        setup               = interface.setup
        handshake_generator = interface.handshakes_out
        tx                  = interface.tx


        #
        # Submodules
        #

        # Handler for Get Descriptor requests; responds with our various fixed descriptors.
        m.submodules.get_descriptor = get_descriptor_handler = GetDescriptorHandler(self.descriptors)
        m.d.comb += [
            get_descriptor_handler.value  .eq(setup.value),
            get_descriptor_handler.length .eq(setup.length),
        ]

        # Handler for various small-constant-response requests (GET_CONFIGURATION, GET_STATUS).
        m.submodules.transmitter = transmitter = \
            StreamSerializer(data_length=2, domain="usb", stream_type=USBInStreamInterface, max_length_width=2)


        #
        # Handlers.
        #
        with m.If(setup.type == USBRequestType.STANDARD):
            with m.FSM(domain="usb"):

                # IDLE -- not handling any active request
                with m.State('IDLE'):

                    # If we've received a new setup packet, handle it.
                    # TODO: limit this to standard requests
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
                            with m.Case():
                                m.next = 'UNHANDLED'


                # GET_STATUS -- Fetch the device's status.
                # For now, we'll always return '0'.
                with m.State('GET_STATUS'):
                    # TODO: handle reporting endpoint stall status
                    # TODO: copy the remote wakeup and bus-powered attributes from bmAttributes of the relevant descriptor?
                    self.handle_simple_data_request(m, transmitter, 0, length=2)


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
                        get_descriptor_handler.tx  .attach(tx),
                        handshake_generator.stall  .eq(get_descriptor_handler.stall)
                    ]

                    # Respond to our data stage with a descriptor...
                    with m.If(interface.data_requested):
                        m.d.comb += get_descriptor_handler.start  .eq(1),

                    # ... and ACK our status stage.
                    with m.If(interface.status_requested):
                        m.d.comb += handshake_generator.ack.eq(1)
                        m.next = 'IDLE'


                # GET_CONFIGURATION -- The host is asking for the active configuration number.
                with m.State('GET_CONFIGURATION'):
                    self.handle_simple_data_request(m, transmitter, interface.active_config)


                # UNHANDLED -- we've received a request we're not prepared to handle
                with m.State('UNHANDLED'):

                    # When we next have an opportunity to stall, do so,
                    # and then return to idle.
                    with m.If(interface.data_requested | interface.status_requested):
                        m.d.comb += handshake_generator.stall.eq(1)
                        m.next = 'IDLE'

        return m


if __name__ == "__main__":
    unittest.main(warnings="ignore")
