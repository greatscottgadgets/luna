#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 physical-layer abstraction."""

import logging

from amaranth import *
from amaranth.lib.cdc import PulseSynchronizer, FFSynchronizer
from amaranth.hdl.ast import Rose


class PHYResetController(Elaboratable):
    """ Gateware responsible for bringing up a PIPE PHY.

    Note that this gateware resides in `sync`, rather than one of our
    SuperSpeed domains, as the SuperSpeed PHY has yet to bring up its clocks.

    Attributes
    ----------
    reset: Signal(), output
        Signal that drives the PHY's ``reset`` signal.

    phy_status: Signal(), input
        The PIPE PHY's phy_status signal; tracks our progress in startup.

    ready: Signal(), output
        Status signal; asserted when the PHY has started up and is ready for use.

    Parameters
    ----------
    sync_frequency: float
        The frequency of the sync clock domain.

    """

    def __init__(self, *, sync_frequency):
        self._sync_frequency = sync_frequency

        #
        # I/O port
        #
        self.reset          = Signal()
        self.ready          = Signal()

        self.phy_status     = Signal()



    def elaborate(self, platform):
        m = Module()

        # Keep track of how many cycles we'll keep our PHY in reset.
        # This is larger than any requirement, in order to work with a broad swathe of PHYs,
        # in case a PHY other than the TUSB1310A ever makes it to the market.
        cycles_in_reset = int(5e-6 * 50e6)
        cycles_spent_in_reset = Signal(range(cycles_in_reset + 1))


        with m.FSM():

            # STARTUP_RESET -- post configuration, we'll reset the PIPE PHY.
            # This is distinct from the PHY's built-in power-on-reset, as we run this
            # on every FPGA configuration.
            with m.State("STARTUP_RESET"):
                m.d.comb += [
                    self.reset        .eq(1),
                ]

                # Once we've extended past a reset time, we can move on.
                m.d.sync += cycles_spent_in_reset.eq(cycles_spent_in_reset + 1)
                with m.If(cycles_spent_in_reset == cycles_in_reset):
                    m.next = "DETECT_PHY_STARTUP"


            # DETECT_PHY_STARTUP -- post-reset, the PHY should drive its status line high.
            # We'll wait for this to happen, so we can track the PHY's progress.
            with m.State("DETECT_PHY_STARTUP"):

                with m.If(self.phy_status):
                    m.next = "WAIT_FOR_STARTUP"


            # WAIT_FOR_STARTUP -- we've now detected that the PHY is starting up.
            # We'll wait for that startup signal to be de-asserted, indicating that the PHY is ready.
            with m.State("WAIT_FOR_STARTUP"):

                # For now, we'll start up in P0. This will change once we implement proper RxDetect.
                with m.If(~self.phy_status):
                    m.next = "READY"


            # READY -- our PHY is all started up and ready for use.
            # For now, we'll remain here until we're reset.
            with m.State("READY"):
                m.d.comb += self.ready.eq(1)


        return m



class LinkPartnerDetector(Elaboratable):
    """ Light abstraction over our PIPE receiver detection mechanism.

    Primarily responsible for the power state sequencing necessary during receiver detection.

    Attributes
    ----------
    request_detection: Signal(), input
        Strobe; requests that a receiver detection will be performed.

    power_state: Signal(2), output
        Controls the PHY's power state signals.
    detection_control: Signal(), output
        Controls the PHY's partner detection signal.
    phy_status: Signal(), input
        Status signal; asserted when the PHY has completed our request.
    rx_status: Signal(3), input
        Status signal; indicates the result of our request.

    new_result: Signal(), output
        Strobe; indicates when a new result is ready on :attr:``partner_present``.
    partner_present: Signal(), output
        High iff a partner was detected during the last detection cycle.

    Parameters
    ----------
    rx_status: Array(Signal(3), Signal(3))
        Read-only view of the PHY's rx_status signal.
    """

    def __init__(self):

        #
        # I/O port
        #
        self.request_detection = Signal()

        self.power_state       = Signal(2, reset=2)
        self.detection_control = Signal()
        self.phy_status        = Signal()
        self.rx_status         = Signal(3)

        self.new_result        = Signal()
        self.partner_present   = Signal()



    def elaborate(self, platform):
        m = Module()

        # Partner detection is indicated by the value `011` being present on RX_STATUS
        # after a detection completes.
        PARTNER_PRESENT_STATUS = 0b011

        with m.FSM(domain="ss"):

            # IDLE_P2 -- our post-startup state; represents when we're IDLE but in P2.
            # This is typically only seen at board startup.
            with m.State("IDLE_P2"):
                m.d.comb += self.power_state.eq(2)

                with m.If(self.request_detection):
                    m.next = "PERFORM_DETECT"


            # PERFORM_DETECT -- we're asking our PHY to perform the core of our detection,
            # and waiting for that detection to complete.
            with m.State("PERFORM_DETECT"):

                # Per [TUSB1310A, 5.3.5.2], we should hold our detection control high until
                # PhyStatus pulses high; when we'll get the results of our detection.
                m.d.comb += [
                    self.power_state        .eq(2),
                    self.detection_control  .eq(1)
                ]

                # When we see PhyStatus strobe high, we know our result is in RxStatus.
                for i in range(2):

                    # When our detection is complete...
                    with m.If(self.phy_status):

                        # ... capture the results, but don't mark ourselves as complete, yet, as we're
                        # still in P2. We'll need to move to operational state.
                        m.d.ss += self.partner_present.eq(self.rx_status == PARTNER_PRESENT_STATUS)
                        m.next = "MOVE_TO_P0"


            # MOVE_TO_P0 -- we've completed a detection, and now are ready to move (back) into our
            # operational state.
            with m.State("MOVE_TO_P0"):

                # Ask the PHY to put us back down in P0.
                m.d.comb += self.power_state.eq(0)

                # Once the PHY indicates it's put us into the relevant power state, we're done.
                # We can now broadcast our result.
                with m.If(self.phy_status):
                    m.d.comb += self.new_result.eq(1)
                    m.next = "IDLE_P0"


            # IDLE_P0 -- our normal operational state; usually reached after at least one detection
            # has completed successfully. We'll wait until another detection is requested.
            with m.State("IDLE_P0"):
                m.d.comb += self.power_state.eq(0)

                # We can only perform detections from P2; so, when the user requests a detection, we'll
                # need to move back to P2.
                with m.If(Rose(self.request_detection)):
                    m.next = "MOVE_TO_P2"


            # MOVE_TO_P2 -- our user has requested a detection, which we can only perform from P2.
            # Accordingly, we'll move to P2, and -then- perform our detection.
            with m.State("MOVE_TO_P2"):

                # Ask the PHY to put us into P2.
                m.d.comb += self.power_state.eq(2)

                # Once the PHY indicates it's put us into the relevant power state, we can begin
                # our link partner detection.
                with m.If(self.phy_status):
                    m.next = "PERFORM_DETECT"


        return m
