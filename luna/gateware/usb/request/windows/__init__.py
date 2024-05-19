#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

from amaranth                                       import Module, Signal

from usb_protocol.emitters.descriptors.microsoft10  import MicrosoftOS10DescriptorCollection
from usb_protocol.types                             import USBRequestRecipient, USBRequestType

from ...usb2.request                                import USBRequestHandler
from .ms_descriptor                                 import GetMicrosoftDescriptorHandlerBlock


class MicrosoftOS10RequestHandler(USBRequestHandler):
    """ A platform-specific handler for Microsoft OS 1.0 requests.

    Parameters
    ----------
    descriptors: MicrosoftOS10DescriptorCollection
        A collection of the platform-specific descriptors to respond to Windows with as requested.
    request_code: 
        Request value defined in the device OS string descriptor (0xEE). This is the byte after 'MSFT100'.
        Also called bMS_VendorCode in Microsoft OS 1.0 descriptor specification.
    max_packet_size
        The maximum packet size for the endpoint associated with this handler.
    """
    def __init__(self, descriptors: MicrosoftOS10DescriptorCollection, request_code=0xee, max_packet_size=64):
        self.descriptors      = descriptors
        self._request_code    = request_code
        self._max_packet_size = max_packet_size

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Create convenience aliases for our interface components.
        interface           = self.interface
        setup               = interface.setup
        handshake_generator = interface.handshakes_out
        tx                  = interface.tx

        # Handler for GET_DESCRIPTOR_SET requests.
        m.submodules.ms_descriptor_handler = ms_descriptor_handler = \
            GetMicrosoftDescriptorHandlerBlock(self.descriptors)
        m.d.comb += [
            ms_descriptor_handler.index   .eq(setup.index),
            ms_descriptor_handler.length  .eq(setup.length),
        ]

        #
        # Handlers.
        #
        with m.If(
            (setup.type == USBRequestType.VENDOR) &
            (setup.request == self._request_code) & (
                ((setup.recipient == USBRequestRecipient.DEVICE) & (setup.index == 4)) |
                ((setup.recipient == USBRequestRecipient.INTERFACE) & (setup.index == 5)))
        ):
            m.d.comb += interface.claim.eq(1)

            with m.FSM(domain='usb'):

                # IDLE -- not handling any active request
                with m.State('IDLE'):

                    m.d.usb += [
                        # Start at the beginning of our next / fresh GET_DESCRIPTOR_SET request.
                        ms_descriptor_handler.start_position   .eq(0),

                        # Always start our responses with DATA1 pids, per [USB 2.0: 8.5.3].
                        interface.tx_data_pid                  .eq(1)
                    ]

                    # If we've received a new setup packet, handle it.
                    with m.If(setup.received):
                        m.next = 'GET_MS_DESCRIPTOR'


                # GET_MS_DESCRIPTOR -- The host is trying to request a OS Feature descriptor set
                with m.State('GET_MS_DESCRIPTOR'):
                    # Keep track of whether we've sent a packet we're expecting an ACK to.
                    expecting_ack = Signal()

                    m.d.comb += [
                        ms_descriptor_handler.tx    .attach(tx),
                        handshake_generator.stall   .eq(ms_descriptor_handler.stall),
                    ]

                    with m.If(interface.data_requested):
                        m.d.comb += ms_descriptor_handler.start.eq(1)
                        m.d.usb += expecting_ack.eq(1)

                    # Each time we receive an ACK, advance in our descriptor.
                    # This allows us to send descriptors with >64B of content.
                    with m.If(interface.handshakes_in.ack & expecting_ack):

                        next_start_position = ms_descriptor_handler.start_position + self._max_packet_size
                        m.d.usb += [
                            # We've received an ACK; so mark the section we've sent of the descriptor as
                            # received, and move forward...
                            ms_descriptor_handler.start_position    .eq(next_start_position),

                            # ... and toggle our data PID.
                            self.interface.tx_data_pid              .eq(~self.interface.tx_data_pid),

                            # We've got the ACK we expected.
                            expecting_ack                           .eq(0),
                        ]

                    # ... and ACK our status stage.
                    with m.If(interface.status_requested):
                        m.d.comb += handshake_generator.ack.eq(1)
                        m.next = 'IDLE'
                    
                    # If the requested descriptor doesn't exist, the request is terminated by STALLing the data stage.
                    with m.Elif(ms_descriptor_handler.stall):
                        m.d.usb += expecting_ack.eq(0)
                        m.next = 'IDLE'

        return m
