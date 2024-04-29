#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Full-gateware control request handlers. """

from amaranth               import *

from ..usb2.request         import USBRequestHandler


class ControlRequestHandler(USBRequestHandler):
    """ Pure-gateware USB control request handler. """


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
