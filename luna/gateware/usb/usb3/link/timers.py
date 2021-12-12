#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" U0 link-maintenance timers. """

from amaranth import *


class LinkMaintenanceTimers(Elaboratable):
    """ Timers which ensure link integrity is maintained in U0.

    These timers ensure that we provide enough traffic to maintain link state,
    and move to link recovery if we ever fail to see constant traffic.

    Our two main rules [USB3.2r1: 7.5.6.1]:
        - If we don't send a link command for 10uS, we'll need to issue a
          keepalive packet in order to keep our link stably in U0.
        - If we don't receive a link command for 1mS, we know that the link
          is no longer in good condition, since the other side should have
          been sending keepalives to prevent this long of an idle. We'll have
          to perform link recovery.


    Attributes
    ----------
    link_command_received: Signal(), input
        Strobe that should be asserted when a link command is received.
    link_command_transmitted: Signal(), input
        Strobe that should be asserted when a link command is transmitted.

    schedule_keepalive: Signal(), output
        Strobe that indicates that we'll need to send a keepalive packet.
    transition_to_recovery: Signal(), output
        Strobe that indicates that our link is no longer stable; and we'll
        need to perform link recovery.

    Parameters
    ----------
    ss_clock_frequency: float
        The frequency of our ``ss`` domain clock, in Hz.
    """

    KEEPALIVE_TIMEOUT = 10e-6
    RECOVERY_TIMEOUT  = 1e-3


    def __init__(self, *, ss_clock_frequency=125e6):
        self._clock_frequency = ss_clock_frequency

        #
        # I/O port.
        #
        self.enable                   = Signal()

        self.link_command_received    = Signal()
        self.packet_received          = Signal()

        self.link_command_transmitted = Signal()

        self.schedule_keepalive       = Signal()
        self.transition_to_recovery   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Note that we don't care about rollover on any of our timers; as it's harmless in
        # both cases. For our keepalive, we'll immediately send a link command, which should
        # clear our timer. For our recovery timer, we'll enter recovery and reset this whole
        # thing anyway. :)


        #
        # Keepalive Timer
        #
        keepalive_timeout_cycles = int(self.KEEPALIVE_TIMEOUT * self._clock_frequency)

        # Time how long it's been since we've sent our last link command.
        keepalive_timer = Signal(range(keepalive_timeout_cycles))
        m.d.comb += self.schedule_keepalive.eq(keepalive_timer + 1 == keepalive_timeout_cycles)

        with m.If(self.link_command_transmitted):
            m.d.ss += keepalive_timer.eq(0)
        with m.Elif(self.enable):
            m.d.ss += keepalive_timer.eq(keepalive_timer + 1)
        with m.Else():
            m.d.ss += keepalive_timer.eq(0)


        #
        # Recovery Timer
        #
        recovery_timeout_cycles = int(self.RECOVERY_TIMEOUT * self._clock_frequency)

        # Time how long it's been since we've received our last link command.
        recovery_timer = Signal(range(recovery_timeout_cycles))
        m.d.comb += self.transition_to_recovery.eq(recovery_timer + 1 == recovery_timeout_cycles)

        with m.If(self.link_command_received | self.packet_received):
            m.d.ss += recovery_timer.eq(0)
        with m.Elif(self.enable):
            m.d.ss += recovery_timer.eq(recovery_timer + 1)
        with m.Else():
            m.d.ss += recovery_timer.eq(0)


        return m
