#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Standard, full-gateware control request handlers. """

import os
import operator
import unittest
import functools
from typing import Iterable, Callable

from luna.gateware.test import utils

from amaranth               import *
from amaranth.hdl.ast       import Value, Const
from usb_protocol.types     import USBStandardRequests, USBRequestType
from usb_protocol.emitters  import DeviceDescriptorCollection

from ..usb2.request         import RequestHandlerInterface, USBRequestHandler
from ..usb2.descriptor      import GetDescriptorHandlerDistributed, GetDescriptorHandlerBlock
from ..stream               import USBInStreamInterface
from ...stream.generator    import StreamSerializer
from luna.gateware.usb.usb2 import descriptor
from .                      import SetupPacket


class StandardRequestHandler(USBRequestHandler):
    """ Pure-gateware USB setup request handler. Implements the standard requests required for enumeration.

    Parameters
    ----------
    descriptors: DeviceDescriptorCollection
        The DeviceDescriptorCollection that contains our descriptors.
    max_packet_size: int, optional
        The maximum packet size for the endpoint associated with this handler.
    blacklist:  iterable of functions that accept a SetupPacket and return a boolean
        Collection of functions that determine if a given packet will be handled by this request handler.
    avoid_blockram: int, optional
        If True, placing data into block RAM will be avoided.

     """

    def __init__(self, descriptors: DeviceDescriptorCollection, max_packet_size=64, avoid_blockram=None, blacklist: Iterable[Callable[[SetupPacket], Value]] = ()):
        self.descriptors      = descriptors
        self._max_packet_size = max_packet_size
        self._avoid_blockram  = avoid_blockram
        self._blacklist = blacklist

        # If we don't have a value for avoiding blockrams; defer to the environment.
        if self._avoid_blockram is None:
            self._avoid_blockram = os.getenv("LUNA_AVOID_BLOCKRAM", False)

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
            Cat(transmitter.data[0:length]).eq(data),
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
        if self._avoid_blockram:
            descriptor_handler_type = GetDescriptorHandlerDistributed
        else:
            descriptor_handler_type = GetDescriptorHandlerBlock

        # Handler for Get Descriptor requests; responds with our various fixed descriptors.
        m.submodules.get_descriptor = get_descriptor_handler = descriptor_handler_type(self.descriptors)
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

                    m.d.usb += [
                        # Start at the beginning of our next / fresh GET_DESCRIPTOR request.
                        get_descriptor_handler.start_position  .eq(0),

                        # Always start our responses with DATA1 pids, per [USB 2.0: 8.5.3].
                        self.interface.tx_data_pid             .eq(1)
                    ]

                    # If we've received a new setup packet, handle it.
                    with m.If(setup.received):

                        # Only handle setup packet if not blacklisted
                        blacklisted = functools.reduce(operator.__or__, (f(setup) for f in self._blacklist), Const(0))
                        with m.If(~blacklisted):

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
                    # Keep track of whether we've sent a packet we're expecting an ACK to.
                    expecting_ack = Signal()

                    m.d.comb += [
                        get_descriptor_handler.tx  .attach(tx),
                        handshake_generator.stall  .eq(get_descriptor_handler.stall)
                    ]

                    # Respond to our data stage with a descriptor...
                    with m.If(interface.data_requested):
                        m.d.comb += get_descriptor_handler.start.eq(1)
                        m.d.usb += expecting_ack.eq(1)

                    # Each time we receive an ACK, advance in our descriptor.
                    # This allows us to send descriptors with >64B of content.
                    with m.If(interface.handshakes_in.ack & expecting_ack):

                        # NOTE: this logic might need to be scaled by bytes-per-word for USB3, if it's ever used.
                        # For now, we're not using it on USB3 at all, since we assume descriptors always fit in a
                        # USB3 packet.
                        next_start_position = get_descriptor_handler.start_position + self._max_packet_size
                        m.d.usb += [

                            # We've received an ACK; so mark the section we've sent of the descriptor as
                            # received, and move forward...
                            get_descriptor_handler.start_position  .eq(next_start_position),

                            # ... and toggle our data PID.
                            self.interface.tx_data_pid             .eq(~self.interface.tx_data_pid),

                            # We've got the ACK we expected.
                            expecting_ack                          .eq(0),
                        ]

                    # ... and ACK our status stage.
                    with m.If(interface.status_requested):
                        m.d.comb += handshake_generator.ack.eq(1)
                        m.next = 'IDLE'

                    # If the requested descriptor doesn't exist, the request is terminated by STALLing the data stage.
                    with m.If(get_descriptor_handler.stall):
                        m.d.usb += expecting_ack.eq(0)
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
