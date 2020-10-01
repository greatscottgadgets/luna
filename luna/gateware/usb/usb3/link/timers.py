#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" U0 link-maintenance timers gateware. """

from nmigen import *

class LinkMaintenanceTimers(Elaboratable):
    """ Timers which ensure link integrity is maintained in U0.

    These timers ensure that we provide enough traffic to maintain link state,
    and move to link recovery if we ever fail to see constant traffic. See [USB3.2r1: 7.5.6.1].

    Attributes
    ----------
    link_command_received: Signal(), input
        Strobe that should be asserted when a link command is received.
    link_command_transmitted: Signal(), input
        Strobe that should be asserted when a link command is transmitted.

    
    """

    def __init__(self, *, ss_clock_frequency=125e6):

        #
        # I/O port.
        #
        self.link_command_received = Signal()


