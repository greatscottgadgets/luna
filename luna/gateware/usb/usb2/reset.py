#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Gateware that handles USB bus resets & speed detection. """

import unittest

from amaranth              import *

from .                     import USBSpeed
from ...interface.utmi     import UTMITransmitInterface, UTMIOperatingMode, UTMITerminationSelect
from ...test               import LunaGatewareTestCase, usb_domain_test_case


def _generate_wide_incrementer(m, platform, adder_input):
    """ Attempts to create an optimal wide-incrementer for counters.

    Yosys on certain platforms (ice40 UltraPlus) doesn't currently use hardware resources
    effectively for wide adders. We'll manually instantiate the relevant resources
    to get rid of an 18-bit carry chain; avoiding a long critical path.

    Parameters:
        platform    -- The platform we're working with.
        adder_input -- The input to our incrementer.
    """

    # If this isn't an iCE40 UltraPlus, let Yosys do its thing.
    if (not platform) or not platform.device.startswith('iCE40UP'):
        return adder_input + 1

    # Otherwise, we'll create a DSP adder itself.
    output = Signal.like(adder_input)
    m.submodules += Instance('SB_MAC16',

        # Hook up our inputs and outputs.
        # A = upper bits of input; B = lower bits of input
        i_A      = adder_input[16:],
        i_B      = adder_input[0:16],
        o_O      = output,

        p_TOPADDSUB_UPPERINPUT =0b1,  # Use as a normal adder
        p_TOPADDSUB_CARRYSELECT=0b11, # Connect our top and bottom adders together.
        p_BOTADDSUB_UPPERINPUT =0b1,  # Use as a normal adder.
        p_BOTADDSUB_CARRYSELECT=0b01  # Always increment.
    )

    return output



class USBResetSequencer(Elaboratable):
    """ Gateware that detects reset signaling on the USB bus.

    Attributes
    ----------
    low_speed_only: Signal(), input
        If set, the device will be forced to operate as a low-speed device.
    prevent_high_speed: Signal(), input
        If set, the device will be prohibited from entering high-speed states; and will thus
        act like it's a full speed device (low_speed_only = 0).
    bus_busy: Signal(), input
        Hold-off signal that indicates that driving the bus should be delayed.
    vbus_connected: Signal(), input
        Indicates that the device is connected to VBUS. When this is de-asserted, the device will
        be held in perpetual bus reset, and reset handshaking will be disabled.
    line_state: Signal(2), input
        The UTMI linestate signals; used to read the current state of the USB D+ and D- lines.

    bus_reset: Signal(), output
        Strobe; pulses high for one cycle when a bus reset is detected. This signal indicates that the
         device should return to unaddressed, unconfigured, and should not longer be in High Speed mode.
    suspended: Signal(), output
        Held high while the USB device should be in suspend. This technically indicates that the device should
        drop down to consuming suspend current (<= 2.5mA), but very few devices are compliant with this requirement.
        Either way, a polite device might reduce its power consumption while in suspend.

    current_speed: Signal(2), output
        A USBSpeed value that indicates the current operating speed. Used both to drive our device's
        knowledge of operating speed and to drive our PHY's speed selection.
    operating_mode: Signal(2), output
        The current UTMI operating mode. Used to select whether we're driving the USB bus directly;
        or whether we're letting the PHY handle NRZI/bit-stuffing.
    termination_select: Signal(), output, default=1
        Determines the bus termination mode. In LS/FS, this determines the presence of our presence-detect
        pull-up. In HS mode, this determines whether the USB high-speed termination is present (0), or
        whether we're in chirp mode (1).

    tx: UTMITransmitInterface, output stream
                     -- Our UTMI transmit interface; used to drive chirp signaling onto the bus.
    """

    # Constants for our line states at various speeds.
    _LINE_STATE_SE0       = 0b00
    _LINE_STATE_SQUELCH   = 0b00
    _LINE_STATE_FS_HS_K   = 0b10
    _LINE_STATE_FS_HS_J   = 0b01
    _LINE_STATE_LS_K      = 0b01
    _LINE_STATE_LS_J      = 0b10

    # Reset time constants.
    # Eventually, if we support clocks other than 60MHz (48 MHz)?
    # We should provide the ability to scale these.
    _CYCLES_500_NANOSECONDS    = 30
    _CYCLES_1_MICROSECOND      = _CYCLES_500_NANOSECONDS  * 2
    _CYCLES_2P5_MICROSECONDS   = _CYCLES_500_NANOSECONDS  * 5
    _CYCLES_5_MICROSECONDS     = _CYCLES_1_MICROSECOND    * 5
    _CYCLES_200_MICROSECONDS   = _CYCLES_1_MICROSECOND    * 200
    _CYCLES_1_MILLISECONDS     = _CYCLES_1_MICROSECOND    * 1000
    _CYCLES_2_MILLISECONDS     = _CYCLES_1_MILLISECONDS   * 2
    _CYCLES_2P5_MILLISECONDS   = _CYCLES_2P5_MICROSECONDS * 1000
    _CYCLES_3_MILLISECONDS     = _CYCLES_1_MILLISECONDS   * 3


    def __init__(self):

        #
        # I/O port
        #
        self.low_speed_only     = Signal()
        self.full_speed_only    = Signal()

        self.bus_busy           = Signal()
        self.vbus_connected     = Signal()
        self.line_state         = Signal(2)

        self.bus_reset          = Signal()
        self.suspended          = Signal()

        self.current_speed      = Signal(2, reset=USBSpeed.FULL)
        self.operating_mode     = Signal(2, reset=UTMIOperatingMode.NORMAL)
        self.termination_select = Signal(1, reset=1)

        self.tx                 = UTMITransmitInterface()


    def elaborate(self, platform):
        m = Module()

        if hasattr(platform, 'ignore_phy_vbus') and platform.ignore_phy_vbus:
            self.vbus_connected = Const(1)

        # Event timer: keeps track of the timing of each of the individual event phases.
        timer = Signal(range(0, self._CYCLES_3_MILLISECONDS + 1))

        # Line state timer: keeps track of how long we've seen a line-state of interest;
        # other than a reset SE0. Used to track chirp and idle times.
        line_state_time = Signal(range(0, self._CYCLES_3_MILLISECONDS + 1))

        # Valid pairs: keeps track of how make Chirp K / Chirp J sequences we've
        # seen, thus far.
        valid_pairs = Signal(range(0, 4))

        # Tracks whether we were at high speed when we entered a suspend state.
        was_hs_pre_suspend = Signal()

        # By default, always count forward in time.
        # We'll reset the timer below when appropriate.
        m.d.usb += timer.eq(_generate_wide_incrementer(m, platform, timer))
        m.d.usb += line_state_time.eq(_generate_wide_incrementer(m, platform, line_state_time))

        # Signal that indicates when the bus is idle.
        # Our bus's IDLE condition depends on our active speed.
        bus_idle = Signal()

        # High speed busses present SE0 (which we see as SQUELCH'd) when idle [USB2.0: 7.1.1.3].
        with m.If(self.current_speed == USBSpeed.HIGH):
            m.d.comb += bus_idle.eq(self.line_state == self._LINE_STATE_SQUELCH)

        # Full and low-speed busses see a 'J' state when idle, due to the device pull-up restistors.
        # (The line_state values for these are flipped between speeds.) [USB2.0: 7.1.7.4.1; USB2.0: Table 7-2].
        with m.Elif(self.current_speed == USBSpeed.FULL):
            m.d.comb += bus_idle.eq(self.line_state == self._LINE_STATE_FS_HS_J)
        with m.Else():
            m.d.comb += bus_idle.eq(self.line_state == self._LINE_STATE_LS_J)


        #
        # Core reset sequences.
        #
        with m.FSM(domain='usb'):

            # INITIALIZE -- we're immediately post-reset; we'll perform some minor setup
            with m.State('INITIALIZE'):

                # If we're working in low-speed mode, configure the PHY accordingly.
                with m.If(self.low_speed_only):
                    m.d.usb += self.current_speed.eq(USBSpeed.LOW)

                m.next = 'LS_FS_NON_RESET'
                m.d.usb += [
                    timer.eq(0),
                    line_state_time.eq(0)
                ]

            # LS_FS_NON_RESET -- we're currently operating at LS/FS and waiting for a reset;
            # the device could be active or inactive, but we haven't yet seen a reset condition.
            with m.State('LS_FS_NON_RESET'):

                # If we're seeing a state other than SE0 (D+ / D- at zero), this isn't yet a
                # potential reset. Keep our timer at zero.
                with m.If(self.line_state != self._LINE_STATE_SE0):
                    m.d.usb += timer.eq(0)


                # If VBUS isn't connected, don't go through the whole reset process;
                # but also consider ourselves permanently in reset. This ensures we
                # don't progress through the reset FSM; but also ensures the device
                # state starts fresh with each plug.
                with m.If(~self.vbus_connected):
                    m.d.usb  += timer.eq(0)
                    m.d.comb += self.bus_reset.eq(1)

                # If we see an SE0 for >2.5uS; < 3ms, this a bus reset.
                # We'll trigger a reset after 5uS; providing a little bit of timing flexibility.
                # [USB2.0: 7.1.7.5; ULPI 3.8.5.1].
                with m.If(timer == self._CYCLES_5_MICROSECONDS):
                    m.d.comb += self.bus_reset.eq(1)

                    # If we're okay to run in high speed, we'll try to perform a high-speed detect.
                    with m.If(~self.low_speed_only & ~self.full_speed_only):
                        m.next = 'START_HS_DETECTION'


                # If we're seeing a state other than IDLE, clear our suspend timer.
                with m.If(~bus_idle):
                    m.d.usb += line_state_time.eq(0)

                # If we see 3ms of consecutive line idle, we're being put into USB suspend.
                # We'll enter our suspended state, directly. [USB2.0: 7.1.7.6]
                with m.If(line_state_time == self._CYCLES_3_MILLISECONDS):
                    m.d.usb += was_hs_pre_suspend.eq(0)
                    m.next = 'SUSPENDED'




            # HS_NON_RESET -- we're currently operating at high speed and waiting for a reset or
            # suspend; the device could be active or inactive.
            with m.State('HS_NON_RESET'):

                # If we're seeing a state other than SE0 (D+ / D- at zero), this isn't yet a
                # potential reset. Keep our timer at zero.
                with m.If(self.line_state != self._LINE_STATE_SE0):
                    m.d.usb += timer.eq(0)

                # If VBUS isn't connected, our device/host relationship is effectively
                # a blank state. We'll want to present our detection pull-up to the host,
                # so we'll drop out of high speed.
                with m.If(~self.vbus_connected):
                    m.d.comb += self.bus_reset.eq(1)
                    m.next = 'IS_LOW_OR_FULL_SPEED'


                # High speed signaling presents IDLE and RESET the same way: with the host
                # driving SE0; and us seeing SQUELCH. [USB2.0: 7.1.1.3; USB2.0: 7.1.7.6].
                # Either way, our next step is the same: we'll drop down to full-speed. [USB2.0: 7.1.7.6]
                # Afterwards, we'll take steps to differentiate a reset from a suspend.
                with m.If(timer == self._CYCLES_3_MILLISECONDS):
                    m.d.usb += [
                        timer                    .eq(0),

                        self.current_speed       .eq(USBSpeed.FULL),
                        self.operating_mode      .eq(UTMIOperatingMode.NORMAL),
                        self.termination_select  .eq(UTMITerminationSelect.LS_FS_NORMAL),
                    ]
                    m.next = 'DETECT_HS_SUSPEND'


                # If we see full-speed-only or low-speed-only being driven, switch
                # back to our LS/FS mode.
                with m.If(self.full_speed_only | self.low_speed_only):
                    m.next = 'IS_LOW_OR_FULL_SPEED'


            # START_HS_DETECTION -- entry state for high-speed detection
            with m.State('START_HS_DETECTION'):
                m.d.usb += [
                    timer                    .eq(0),

                    # Switch into High-speed chirp mode. Note that we'll need to leave our
                    # terminations set to '1' until we're sure this is a high-speed host;
                    # or the host will see our pull-up removal as a disconnect.
                    self.current_speed       .eq(USBSpeed.HIGH),
                    self.operating_mode      .eq(UTMIOperatingMode.CHIRP),
                    self.termination_select  .eq(UTMITerminationSelect.HS_CHIRP)
                ]
                m.next = 'PREPARE_FOR_CHIRP_0'


            # PREPARE_FOR_CHIRP_0 / PREPARE_FOR_CHIRP_1-- wait states; in which we give the PHY
            # time to the mode we'll need to drive our high-speed chirp.
            with m.State('PREPARE_FOR_CHIRP_0'):
                with m.If(~self.bus_busy):
                    m.next = 'PREPARE_FOR_CHIRP_1'

            with m.State('PREPARE_FOR_CHIRP_1'):
                with m.If(~self.bus_busy):
                    m.next = 'DEVICE_CHIRP'


            # DEVICE_CHIRP -- the device produces a 'chirp' K, which advertises to the host that
            # we're high speed capable. We'll provide that chirp K for around ~2ms. [USB2.0: 7.1.7.5]
            with m.State('DEVICE_CHIRP'):

                # Transmit a constant stream of 0's, which in this mode is a Chirp K.
                # Note that we don't need to check 'ready', as we care about the length
                # of time, rather than the number of bits.
                m.d.comb += [
                    self.tx.valid  .eq(1),
                    self.tx.data   .eq(0)
                ]

                # Once 2ms have passed, we can stop our chirp, and begin waiting for the
                # hosts's response. We'll wait for Ready to be asserted to do so, to ensure
                # we don't change our values in the middle of a bit.
                with m.If((timer == self._CYCLES_2_MILLISECONDS)):
                    m.d.usb += [
                        timer        .eq(0),
                        valid_pairs  .eq(0)
                    ]
                    m.next = 'AWAIT_HOST_K'


            # AWAIT_HOST_K -- we've now completed the device chirp; and are waiting to see if the host
            # will respond with an alternating sequence of K's and J's.
            with m.State('AWAIT_HOST_K'):

                # If we don't see our response within 2.5ms, this isn't a compliant HS host. [USB2.0: 7.1.7.5].
                # This is thus a full-speed host, and we'll act as a full-speed device.
                with m.If(timer == self._CYCLES_2P5_MILLISECONDS):
                    m.next = 'IS_LOW_OR_FULL_SPEED'

                # Once we've seen our K, we're good to start observing J/K toggles.
                with m.If(self.line_state == self._LINE_STATE_FS_HS_K):
                    m.next = 'IN_HOST_K'
                    m.d.usb += line_state_time.eq(0)


            # IN_HOST_K: we're seeing a host Chirp K as part of our handshake; we'll
            # time it and see how long it lasts
            with m.State('IN_HOST_K'):

                # If we've exceeded our minimum chirp time, consider this a valid pattern
                # bit, # and advance in the pattern.
                with m.If(line_state_time == self._CYCLES_2P5_MICROSECONDS):
                    m.next = 'AWAIT_HOST_J'

                # If our input has become something other than a K, then
                # we haven't finished our sequence. We'll go back to expecting a K.
                with m.If(self.line_state != self._LINE_STATE_FS_HS_K):
                    m.next = 'AWAIT_HOST_K'

                # Time out if we exceed our maximum allowed duration.
                with m.If(timer == self._CYCLES_2P5_MILLISECONDS):
                    m.next = 'IS_LOW_OR_FULL_SPEED'


            # AWAIT_HOST_J -- we're waiting for the next Chirp J in the host chirp sequence
            with m.State('AWAIT_HOST_J'):

                # If we've exceeded our maximum wait, this isn't a high speed host.
                with m.If(timer == self._CYCLES_2P5_MILLISECONDS):
                    m.next = 'IS_LOW_OR_FULL_SPEED'

                # Once we've seen our J, start timing its duration.
                with m.If(self.line_state == self._LINE_STATE_FS_HS_J):
                    m.next = 'IN_HOST_J'
                    m.d.usb += line_state_time.eq(0)


            # IN_HOST_J: we're seeing a host Chirp K as part of our handshake; we'll
            # time it and see how long it lasts
            with m.State('IN_HOST_J'):

                # If we've exceeded our minimum chirp time, consider this a valid pattern
                # bit, and advance in the pattern.
                with m.If(line_state_time == self._CYCLES_2P5_MICROSECONDS):

                    # If this would complete our third pair, this completes a handshake,
                    # and we've identified a high speed host!
                    with m.If(valid_pairs == 2):
                        m.next = 'IS_HIGH_SPEED'

                    # Otherwise, count the pair as valid, and wait for the next K.
                    with m.Else():
                        m.d.usb += valid_pairs.eq(valid_pairs + 1)
                        m.next = 'AWAIT_HOST_K'

                # If our input has become something other than a K, then
                # we haven't finished our sequence. We'll go back to expecting a K.
                with m.If(self.line_state != self._LINE_STATE_FS_HS_J):
                    m.next = 'AWAIT_HOST_J'

                # Time out if we exceed our maximum allowed duration.
                with m.If(timer == self._CYCLES_2P5_MILLISECONDS):
                    m.next = 'IS_LOW_OR_FULL_SPEED'


            # IS_HIGH_SPEED -- we've completed a high speed handshake, and are ready to
            # switch to high speed signaling
            with m.State('IS_HIGH_SPEED'):

                # Switch to high speed.
                m.d.usb += [
                    timer                    .eq(0),
                    line_state_time          .eq(0),

                    self.current_speed       .eq(USBSpeed.HIGH),
                    self.operating_mode      .eq(UTMIOperatingMode.NORMAL),
                    self.termination_select  .eq(UTMITerminationSelect.HS_NORMAL)
                ]

                m.next = 'HS_NON_RESET'


            # IS_LOW_OR_FULL_SPEED -- we've decided the device is low/full speed (typically
            # because it didn't) complete our high-speed handshake; set it up accordingly.
            with m.State('IS_LOW_OR_FULL_SPEED'):
                m.d.usb += [
                    self.operating_mode      .eq(UTMIOperatingMode.NORMAL),
                    self.termination_select  .eq(UTMITerminationSelect.LS_FS_NORMAL)
                ]

                # If we're operating in low-speed only, drop down to low speed.
                with m.If(self.low_speed_only):
                    m.d.usb += self.current_speed.eq(USBSpeed.LOW),

                # Otherwise, drop down to full speed.
                with m.Else():
                    m.d.usb += self.current_speed.eq(USBSpeed.FULL)

                # Once we know that our reset is complete, move back to our normal, non-reset state.
                with m.If(self.line_state != self._LINE_STATE_SE0):
                    m.next = 'LS_FS_NON_RESET'
                    m.d.usb += [
                        timer.eq(0),
                        line_state_time.eq(0)
                    ]


            # DETECT_HS_SUSPEND -- we were operating at high speed, and just detected an event
            # which is either a reset or a suspend event; we'll now detect which.
            with m.State('DETECT_HS_SUSPEND'):

                # We've just switch from HS signaling to FS signaling.
                # We'll wait a little while for the bus to settle, and then
                # check to see if it's settled to FS idle; or if we still see SE0.
                with m.If(timer == self._CYCLES_200_MICROSECONDS):
                    m.d.usb += timer.eq(0)

                    # If we've resume IDLE, this is suspend. Move to HS suspend.
                    with m.If(self.line_state == self._LINE_STATE_FS_HS_J):
                        m.d.usb += was_hs_pre_suspend.eq(1)
                        m.next = 'SUSPENDED'

                    # Otherwise, this is a reset (or, if K/SE1, we're very confused, and
                    # should re-initialize anyway). Move to the HS reset detect sequence.
                    with m.Else():
                        m.d.comb += self.bus_reset.eq(1)
                        m.next = 'START_HS_DETECTION'


            # SUSPEND -- our device has entered USB suspend; we'll now wait for either a
            # resume or a reset
            with m.State('SUSPENDED'):
                m.d.comb += self.suspended.eq(1)

                # If we see a K state, then we're being resumed.
                is_ls_k = self.low_speed_only  & (self.line_state == self._LINE_STATE_LS_K)
                is_fs_k = ~self.low_speed_only & (self.line_state == self._LINE_STATE_FS_HS_K)
                with m.If(is_ls_k | is_fs_k):
                    m.d.usb  += timer.eq(0)

                    # If we were in high-speed pre-suspend, then resume being in HS.
                    with m.If(was_hs_pre_suspend):
                        m.next = 'IS_HIGH_SPEED'

                    # Otherwise, just resume.
                    with m.Else():
                        m.next = 'LS_FS_NON_RESET'
                        m.d.usb += [
                            timer.eq(0),
                            line_state_time.eq(0)
                        ]


                # If this isn't an SE0, we're not receiving a reset request.
                # Keep our reset counter at zero.
                with m.If(self.line_state != self._LINE_STATE_SE0):
                    m.d.usb += timer.eq(0)


                # If we see an SE0 for > 2.5uS, this is a reset request. [USB 2.0: 7.1.7.5]
                # We'll handle it directly from suspend.
                with m.If(timer == self._CYCLES_2P5_MICROSECONDS):
                    m.d.comb += self.bus_reset.eq(1)
                    m.d.usb  += timer.eq(0)

                    # If we're limited to LS or FS, move to the appropriate state.
                    with m.If(self.low_speed_only | self.full_speed_only):
                        m.next = 'LS_FS_NON_RESET'
                        m.d.usb += [
                            timer.eq(0),
                            line_state_time.eq(0)
                        ]

                    # Otherwise, this could be a high-speed device; enter its reset.
                    with m.Else():
                        m.next = 'START_HS_DETECTION'

        return m


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

        # After assertion of SE0, we should remain out of reset for 2.5uS...
        yield
        self.assertEqual((yield dut.bus_reset), 0)

        # ... and then we should see a cycle of reset.
        yield from self.advance_cycles(dut._CYCLES_2P5_MICROSECONDS + 1)
        self.assertEqual((yield dut.bus_reset), 1)

        yield from self.advance_cycles(10)
        yield dut.line_state.eq(0b01)
        yield

        # Finally, we should arrive in FS, post-reset.
        self.assertEqual((yield dut.current_speed),      USBSpeed.FULL)
        self.assertEqual((yield dut.operating_mode),     UTMIOperatingMode.NORMAL)
        self.assertEqual((yield dut.termination_select), UTMITerminationSelect.LS_FS_NORMAL)


    #
    # It would be lovely to have tests that run through each of our reset/suspend
    # cases here; but currently the time it takes run through the relevant delays is
    # prohibitive. :(
    #


if __name__ == "__main__":
    unittest.main()
