#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Clock and reset (CAR) controllers for LUNA. """

import logging

from abc import ABCMeta, abstractmethod
from amaranth import Signal, Module, ClockDomain, ClockSignal, Elaboratable, Instance, ResetSignal

from ..utils.cdc import stretch_strobe_signal
from ..test      import LunaGatewareTestCase, usb_domain_test_case, sync_test_case


class PHYResetController(Elaboratable):
    """ Gateware that implements a short power-on-reset pulse to reset an attached PHY.

    I/O ports:

        I: trigger   -- A signal that triggers a reset when high.
        O: phy_reset -- The signal to be delivered to the target PHY.
    """

    def __init__(self, *, clock_frequency=60e6, reset_length=2e-6, stop_length=2e-6, power_on_reset=True):
        """ Params:

            reset_length   -- The length of a reset pulse, in seconds.
            stop_length    -- The length of time STP should be asserted after reset.
            power_on_reset -- If True or omitted, the reset will be applied once the firmware
                              is configured.
        """

        from math import ceil

        self.power_on_reset = power_on_reset

        # Compute the reset length in cycles.
        clock_period = 1 / clock_frequency
        self.reset_length_cycles = ceil(reset_length / clock_period)
        self.stop_length_cycles  = ceil(stop_length  / clock_period)

        #
        # I/O port
        #
        self.trigger   = Signal()
        self.phy_reset = Signal()
        self.phy_stop  = Signal()


    def elaborate(self, platform):
        m = Module()

        # Counter that stores how many cycles we've spent in reset.
        cycles_in_reset = Signal(range(0, self.reset_length_cycles))

        reset_state = 'RESETTING' if self.power_on_reset else 'IDLE'
        with m.FSM(reset=reset_state, domain='sync') as fsm:

            # Drive the PHY reset whenever we're in the RESETTING cycle.
            m.d.comb += [
                self.phy_reset.eq(fsm.ongoing('RESETTING')),
                self.phy_stop.eq(~fsm.ongoing('IDLE'))
            ]

            with m.State('IDLE'):
                m.d.sync += cycles_in_reset.eq(0)

                # Wait for a reset request.
                with m.If(self.trigger):
                    m.next = 'RESETTING'

            # RESETTING: hold the reset line active for the given amount of time
            with m.State('RESETTING'):
                m.d.sync += cycles_in_reset.eq(cycles_in_reset + 1)

                with m.If(cycles_in_reset + 1 == self.reset_length_cycles):
                    m.d.sync += cycles_in_reset.eq(0)
                    m.next = 'DEFERRING_STARTUP'

            # DEFERRING_STARTUP: Produce a signal that will defer startup for
            # the provided amount of time. This allows line state to stabilize
            # before the PHY will start interacting with us.
            with m.State('DEFERRING_STARTUP'):
                m.d.sync += cycles_in_reset.eq(cycles_in_reset + 1)

                with m.If(cycles_in_reset + 1 == self.stop_length_cycles):
                    m.d.sync += cycles_in_reset.eq(0)
                    m.next = 'IDLE'


        return m



class PHYResetControllerTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = PHYResetController

    def initialize_signals(self):
        yield self.dut.trigger.eq(0)

    @sync_test_case
    def test_power_on_reset(self):

        #
        # After power-on, the PHY should remain in reset for a while.
        #
        yield
        self.assertEqual((yield self.dut.phy_reset), 1)

        yield from self.advance_cycles(30)
        self.assertEqual((yield self.dut.phy_reset), 1)

        yield from self.advance_cycles(60)
        self.assertEqual((yield self.dut.phy_reset), 1)

        #
        # Then, after the relevant reset time, it should resume being unasserted.
        #
        yield from self.advance_cycles(31)
        self.assertEqual((yield self.dut.phy_reset), 0)
        self.assertEqual((yield self.dut.phy_stop),  1)

        yield from self.advance_cycles(120)
        self.assertEqual((yield self.dut.phy_stop),  0)



class LunaDomainGenerator(Elaboratable, metaclass=ABCMeta):
    """ Helper that generates the clock domains used in a LUNA board.

    Note that this module should create three in-phase clocks; so these domains
    should not require explicit boundary crossings.

    I/O port:
        O: clk_fast      -- The clock signal for our fast clock domain.
        O: clk_sync      -- The clock signal used for our sync clock domain.
        O: clk_usb       -- The clock signal used for our USB domain.
        O: usb_holdoff   -- Signal that indicates that the USB domain is immediately post-reset,
                            and thus we should avoid transactions with the external PHY.
    """

    def __init__(self, *, clock_signal_name=None):
        """
        Parameters:
            clock_signal_name = The clock signal name to use; or None to use the platform's default clock.
        """

        self.clock_name = clock_signal_name

        #
        # I/O port
        #
        self.clk_fast     = Signal()
        self.clk_sync     = Signal()
        self.clk_usb      = Signal()

        self.usb_holdoff  = Signal()


    @abstractmethod
    def generate_fast_clock(self, m, platform):
        """ Method that returns our platform's fast clock; used for e.g. RAM interfacing. """


    @abstractmethod
    def generate_sync_clock(self, m, platform):
        """ Method that returns our platform's primary synchronous clock. """


    @abstractmethod
    def generate_usb_clock(self, m, platform):
        """ Method that generates a 60MHz clock used for ULPI interfacing. """


    def create_submodules(self, m, platform):
        """ Method hook for creating any necessary submodules before generating clock. """
        pass


    def create_usb_reset(self, m, platform):
        """
        Function that should create our USB reset, and connect it to:
            m.domains.usb.rst / self.usb_rst
        """

        m.submodules.usb_reset = controller = PHYResetController()
        m.d.comb += [
            ResetSignal("usb")  .eq(controller.phy_reset),
            self.usb_holdoff    .eq(controller.phy_stop)
        ]


    def elaborate(self, platform):
        m = Module()

        # Create our clock domains.
        m.domains.fast = self.fast = ClockDomain()
        m.domains.sync = self.sync = ClockDomain()
        m.domains.usb  = self.usb  = ClockDomain()

        # Call the hook that will create any submodules necessary for all clocks.
        self.create_submodules(m, platform)

        # Generate and connect up our clocks.
        m.d.comb += [
            self.clk_usb                   .eq(self.generate_usb_clock(m, platform)),
            self.clk_sync                  .eq(self.generate_sync_clock(m, platform)),
            self.clk_fast                  .eq(self.generate_fast_clock(m, platform)),

            ClockSignal(domain="fast")     .eq(self.clk_fast),
            ClockSignal(domain="sync")     .eq(self.clk_sync),
            ClockSignal(domain="usb")      .eq(self.clk_usb),
        ]

        # Call the hook that will connect up our reset signals.
        self.create_usb_reset(m, platform)

        return m


class LunaECP5DomainGenerator(LunaDomainGenerator):
    """ ECP5 clock domain generator for LUNA. Assumes a 60MHz input clock. """

    # For debugging, we'll allow the ECP5's onboard clock to generate a 62MHz
    # oscillator signal. This won't work for USB, but it'll at least allow
    # running some basic self-tests. The clock is 310 MHz by default, so
    # dividing by 5 will yield 62MHz.
    OSCG_DIV = 5

    # Quick configuration selection
    DEFAULT_CLOCK_FREQUENCIES_MHZ = {
        "fast": 240,
        "sync": 120,
        "usb":  60
    }

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        """
        Parameters:
            clock_frequencies -- A dictionary mapping 'fast', 'sync', and 'usb' to the clock
                                 frequencies for those domains, in MHz. Valid choices for each
                                 domain are 60, 120, and 240. If not provided, fast will be
                                 assumed to be 240, sync will assumed to be 120, and usb will
                                 be assumed to be a standard 60.
        """
        super().__init__(clock_signal_name=clock_signal_name)
        self.clock_frequencies = clock_frequencies


    def create_submodules(self, m, platform):

        self._pll_lock   = Signal()


        # Figure out our platform's clock frequencies -- grab the platform's
        # defaults, and then override any with our local, caller-provided copies.
        new_clock_frequencies = platform.DEFAULT_CLOCK_FREQUENCIES_MHZ.copy()
        if self.clock_frequencies:
            new_clock_frequencies.update(self.clock_frequencies)
        self.clock_frequencies = new_clock_frequencies


        # Use the provided clock name for our input; or the default clock
        # if no name was provided.
        clock_name = self.clock_name if self.clock_name else platform.default_clk

        # Create absolute-frequency copies of our PLL outputs.
        # We'll use the generate_ methods below to select which domains
        # apply to which components.
        self._clk_240MHz = Signal()
        self._clk_120MHz = Signal()
        self._clk_60MHz  = Signal()
        self._clock_options = {
            60:  self._clk_60MHz,
            120: self._clk_120MHz,
            240: self._clk_240MHz
        }

        # Grab our input clock
        # For debugging: if our clock name is "OSCG", allow using the internal
        # oscillator. This is mostly useful for debugging.
        if clock_name == "OSCG":
            logging.warning("Using FPGA-internal oscillator for an approximately 62MHz.")
            logging.warning("USB communication won't work for f_OSC != 60MHz.")

            input_clock = Signal()
            m.submodules += Instance("OSCG", p_DIV=self.OSCG_DIV, o_OSC=input_clock)
        else:
            input_clock = platform.request(clock_name)

        # Instantiate the ECP5 PLL.
        # These constants generated by Clarity Designer; which will
        # ideally be replaced by an open-source component.
        # (see https://github.com/SymbiFlow/prjtrellis/issues/34.)
        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=input_clock,

                # Generated clock outputs.
                o_CLKOP=self._clk_240MHz,
                o_CLKOS=self._clk_120MHz,
                o_CLKOS2=self._clk_60MHz,

                # Status.
                o_LOCK=self._pll_lock,

                # PLL parameters...
                p_PLLRST_ENA="DISABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_CLKOS3_FPHASE=0,
                p_CLKOS3_CPHASE=0,
                p_CLKOS2_FPHASE=0,
                p_CLKOS2_CPHASE=7,
                p_CLKOS_FPHASE=0,
                p_CLKOS_CPHASE=3,
                p_CLKOP_FPHASE=0,
                p_CLKOP_CPHASE=1,
                p_PLL_LOCK_MODE=0,
                p_CLKOS_TRIM_DELAY="0",
                p_CLKOS_TRIM_POL="FALLING",
                p_CLKOP_TRIM_DELAY="0",
                p_CLKOP_TRIM_POL="FALLING",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKOS3_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXC="DIVC",
                p_CLKOS2_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXB="DIVB",
                p_CLKOS_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOS3_DIV=1,
                p_CLKOS2_DIV=8,
                p_CLKOS_DIV=4,
                p_CLKOP_DIV=2,
                p_CLKFB_DIV=4,
                p_CLKI_DIV=1,
                p_FEEDBK_PATH="CLKOP",

                # Internal feedback.
                i_CLKFB=self._clk_240MHz,

                # Control signals.
                i_RST=0,
                i_PHASESEL0=0,
                i_PHASESEL1=0,
                i_PHASEDIR=0,
                i_PHASESTEP=0,
                i_PHASELOADREG=0,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS=0,
                i_ENCLKOS2=0,
                i_ENCLKOS3=0,

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="60.000000",
                a_FREQUENCY_PIN_CLKOS2="60.000000",
                a_FREQUENCY_PIN_CLKOS="120.000000",
                a_FREQUENCY_PIN_CLKOP="240.000000",
                a_ICP_CURRENT="9",
                a_LPF_RESISTOR="8"
        )


        # Set up our global resets so the system is kept fully in reset until
        # our core PLL is fully stable. This prevents us from internally clock
        # glitching ourselves before our PLL is locked. :)
        m.d.comb += [
            ResetSignal("sync").eq(~self._pll_lock),
            ResetSignal("fast").eq(~self._pll_lock),
        ]


    def generate_usb_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['usb']]

    def generate_sync_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['sync']]

    def generate_fast_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['fast']]


    def stretch_sync_strobe_to_usb(self, m, strobe, output=None, allow_delay=False):
        """
        Helper that stretches a strobe from the `sync` domain to communicate with the `usn` domain.
        Works for any chosen frequency in which f(usb) < f(sync).
        """

        # TODO: replace with Amaranth's pulsesynchronizer?
        to_cycles = self.clock_frequencies['sync'] // self.clock_frequencies['usb']
        return stretch_strobe_signal(m, strobe, output=output, to_cycles=to_cycles, allow_delay=allow_delay)
