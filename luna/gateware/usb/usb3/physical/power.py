#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 physical-layer abstraction."""

import logging

from nmigen import *
from nmigen.lib.cdc import PulseSynchronizer, FFSynchronizer


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
        self.power_state    = Signal(2)

        self.phy_status     = Signal()



    def elaborate(self, platform):
        m = Module()

        # Keep track of how many cycles we'll keep our PHY in reset.
        # This is larger than any requirement, in order to work with a broad swathe of PHYs,
        # in case a PHY other than the TUSB1310A ever makes it to the market.
        cycles_in_reset = int(2e-6 * 50e6)
        cycles_left_in_reset = Signal(range(cycles_in_reset), reset=cycles_in_reset - 1)

        # Create versions of our phy_status signals that are observable:
        # 1) as an asynchronous inputs for startup pulses
        # 2) as a single-cycle pulse, for power-state-change notifications
        phy_status       = Signal()
        phy_status_pulse = Signal()

        # Asynchronous input synchronizer...
        m.submodules += FFSynchronizer(self.phy_status, phy_status),

        # ... and pulse synchronizer.
        m.submodules.pulse_sync = pulse_sync = PulseSynchronizer(i_domain="ss_io", o_domain="sync")
        m.d.comb += [
            pulse_sync.i      .eq(self.phy_status),
            phy_status_pulse  .eq(pulse_sync.o)
        ]


        with m.FSM():

            # STARTUP_RESET -- post configuration, we'll reset the PIPE PHY.
            # This is distinct from the PHY's built-in power-on-reset, as we run this
            # on every FPGA configuration.
            with m.State("STARTUP_RESET"):
                m.d.comb += [
                    self.reset        .eq(1),
                    self.power_state  .eq(2)
                ]

                # Once we've extended past a reset time, we can move on.
                m.d.sync += cycles_left_in_reset.eq(cycles_left_in_reset - 1)
                with m.If(cycles_left_in_reset == 0):
                    m.next = "DETECT_PHY_STARTUP"


            # DETECT_PHY_STARTUP -- post-reset, the PHY should drive its status line high.
            # We'll wait for this to happen, so we can track the PHY's progress.
            with m.State("DETECT_PHY_STARTUP"):

                with m.If(phy_status):
                    m.next = "WAIT_FOR_STARTUP"


            # WAIT_FOR_STARTUP -- we've now detected that the PHY is starting up.
            # We'll wait for that startup signal to be de-asserted, indicating that the PHY is ready.
            with m.State("WAIT_FOR_STARTUP"):

                # For now, we'll start up in P0. This will change once we implement proper RxDetect.
                with m.If(~phy_status):
                    m.next = "READY"


            # READY -- our PHY is all started up and ready for use.
            # For now, we'll remain here until we're reset.
            with m.State("READY"):
                m.d.comb += self.ready.eq(1)


        return m


