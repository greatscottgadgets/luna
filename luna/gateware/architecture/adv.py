#
# This file is part of LUNA.
#
# Copyright (c) 2023 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Controllers for communicating with Apollo through the FPGA_ADV pin """

from amaranth                       import Elaboratable, Module, Signal, Mux
from amaranth_stdio.serial          import AsyncSerialTX

from luna.gateware.usb.usb2.request import USBRequestHandler
from usb_protocol.types             import USBRequestType


class ApolloAdvertiser(Elaboratable):
    """ Gateware that implements a periodic announcement to Apollo using the FPGA_ADV pin.

    Currently it is used to tell Apollo that the gateware wants to use the CONTROL port.
    Apollo will keep the port switch connected to the FPGA after a reset as long as this 
    message is received periodically.
    Once the port is lost, Apollo will ignore further messages until a specific vendor 
    request is called.

    I/O ports:
        I: stop -- Advertisement messages are stopped if this line is asserted.
    """
    def __init__(self):
        self.stop = Signal()

    def default_request_handler(self):
        return ApolloAdvertiserRequestHandler(self.stop)

    def elaborate(self, platform):
        m = Module()

        clk_freq = platform.DEFAULT_CLOCK_FREQUENCIES_MHZ["sync"] * 1e6

        # Communication is done with a serial transmitter (unidirectional)
        baudrate = 9600
        divisor  = int(clk_freq // baudrate)
        fpga_adv = AsyncSerialTX(divisor=divisor, data_bits=8, parity="even")
        m.submodules += fpga_adv

        # Counter with 50ms period
        period    = int(clk_freq * 50e-3)
        timer     = Signal(range(period))
        m.d.sync += timer.eq(Mux(timer == period-1, 0, timer+1))

        # Trigger announcement when the counter overflows
        m.d.comb += [
            fpga_adv.data .eq(ord('A')),
            fpga_adv.ack  .eq((timer == 0) & ~self.stop),
        ]
        
        # Drive the FPGA_ADV pin with the serial transmitter
        m.d.comb += platform.request("int").o.eq(fpga_adv.o)
        
        return m


class ApolloAdvertiserRequestHandler(USBRequestHandler):
    """ Request handler for ApolloAdvertiser. 
    
    Implements default vendor requests related to ApolloAdvertiser.
    """
    REQUEST_APOLLO_ADV_STOP = 0xF0

    def __init__(self, stop_pin=None):
        super().__init__()
        self.stop_pin = stop_pin

    def elaborate(self, platform):
        m = Module()

        interface         = self.interface
        setup             = self.interface.setup

        #
        # Vendor request handlers.

        with m.If(setup.type == USBRequestType.VENDOR):
            with m.Switch(setup.request):

                with m.Case(self.REQUEST_APOLLO_ADV_STOP):

                    # Once the receive is complete, respond with an ACK.
                    with m.If(interface.rx_ready_for_response):
                        m.d.comb += interface.handshakes_out.ack.eq(1)

                    # If we reach the status stage, send a ZLP.
                    with m.If(interface.status_requested):
                        m.d.comb += self.send_zlp()
                        m.d.usb += self.stop_pin.eq(1)

                with m.Case():

                    #
                    # Stall unhandled requests.
                    #
                    with m.If(interface.status_requested | interface.data_requested):
                        m.d.comb += interface.handshakes_out.stall.eq(1)

                return m
