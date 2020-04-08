#
# This file is part of LUNA.
#
""" Gateware that handles USB bus resets & speed detection. """


from nmigen                import Signal, Module, Elaboratable


class USBResetSequencer(Elaboratable):
    """ Gateware that detects reset signaling on the USB bus.

    I/O port:
        I: speed[2]      -- The current operating speed of the USB device. This is used to
                            detect when we're operating at low speed; at which we skip trying
                            the high-speed detection protocol.
        I: line_state[2] -- The UTMI linestate signals; used to read the current state of
                            the USB D+ and D- lines.

        O: bus_reset     -- Strobe; pulses high for one cycle when a bus reset is detected.
                            This signal indicates that the device should return to unaddressed,
                            unconfigured, and should not longer be in High Speed mode.
    """


    def __init__(self):

        #
        # I/O port
        #
        self.line_state = Signal(2)
        self.speed      = Signal(2)

        self.bus_reset  = Signal()


    def elaborate(self, platform):
        m = Module()

        # Event timer.
        # Keeps track of the timing of each of the individual event phases.
        timer = Signal(range(0, 60_000))

        # By default, always count forward in time.
        # We'll reset the timer below when appropriate.
        m.d.usb += timer.eq(timer + 1)


        #
        # Core reset sequences.
        #
        with m.FSM():

            # NOT_IN_RESET -- we're waiting for a reset; the device could be active or inactive,
            # but we haven't yet seen a reset condition.
            with m.State('NOT_IN_RESET'):

                # If we're seeing a state other than SE0 (D+ / D- at zero), this isn't yet a
                # potential reset. Keep our timer at zero.
                with m.If(self.line_state != 0b00):
                    m.d.usb += timer.eq(0)


                # If we see an SE0 for 2.5uS (150 UTMI/ULPI cycles), this a bus reset.
                # [USB2.0 7.1.7.5; ULPI 3.8.5.1].
                with m.If(timer > 150):
                    m.d.comb += self.bus_reset.eq(1)


        return m


