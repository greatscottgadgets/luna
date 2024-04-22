#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.test           import LunaGatewareTestCase, usb_domain_test_case

from luna.gateware.usb.usb2       import USBSpeed
from luna.gateware.usb.usb2.reset import USBResetSequencer
from luna.gateware.interface.utmi     import UTMIOperatingMode, UTMITerminationSelect

class USBResetSequencerTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = USBResetSequencer

    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY  = 60e6

    def instantiate_dut(self):
        dut = super().instantiate_dut()

        # Test tweak: squish down our delays to speed up sim.
        dut._CYCLES_2P5_MICROSECONDS = 10

        return dut


    def initialize_signals(self):

        # Start with a non-reset line-state.
        yield self.dut.line_state.eq(0b01)

    @usb_domain_test_case
    def test_full_speed_reset(self):
        dut = self.dut

        yield from self.advance_cycles(10)

        # Before we detect a reset, we should be at normal FS,
        # and we should be in reset until VBUS is provided.
        self.assertEqual((yield dut.bus_reset),          1)
        self.assertEqual((yield dut.current_speed),      USBSpeed.FULL)
        self.assertEqual((yield dut.operating_mode),     UTMIOperatingMode.NORMAL)
        self.assertEqual((yield dut.termination_select), UTMITerminationSelect.LS_FS_NORMAL)

        # Once we apply VBUS, we should drop out of reset...
        yield dut.vbus_connected.eq(1)
        yield
        self.assertEqual((yield dut.bus_reset), 0)

        # ... and stay that way.
        yield from self.advance_cycles(dut._CYCLES_2P5_MICROSECONDS)
        self.assertEqual((yield dut.bus_reset), 0)

        yield dut.line_state.eq(0)

        # After assertion of SE0, we should remain out of reset for >2.5us, <3ms...
        yield
        self.assertEqual((yield dut.bus_reset), 0)

        # ... we choose to wait for 5us and then we should see a cycle of reset.
        yield from self.advance_cycles(dut._CYCLES_5_MICROSECONDS)
        self.assertEqual((yield dut.bus_reset), 1)

        yield from self.advance_cycles(10)
        yield dut.line_state.eq(0b01)
        yield

        # Finally, we should arrive in HS_DETECT, post-reset.
        self.assertEqual((yield dut.current_speed),      USBSpeed.HIGH)
        self.assertEqual((yield dut.operating_mode),     UTMIOperatingMode.CHIRP)
        self.assertEqual((yield dut.termination_select), UTMITerminationSelect.HS_CHIRP)


    #
    # It would be lovely to have tests that run through each of our reset/suspend
    # cases here; but currently the time it takes run through the relevant delays is
    # prohibitive. :(
    #
