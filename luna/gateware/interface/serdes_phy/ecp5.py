#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2020 whitequark@whitequark.org
#
# The ECP5's DCU parameters/signals/instance have been partially documented by whitequark
# as part of the Yumewatari project: https://github.com/whitequark/Yumewatari.
#
# Code based in part on ``litex`` and ``liteiclink``.
# SPDX-License-Identifier: BSD-3-Clause
""" Soft PIPE backend for the Lattice ECP5 SerDes. """


from amaranth import *
from amaranth.lib.cdc import FFSynchronizer

from .lfps         import LFPSSquareWaveGenerator, LFPSSquareWaveDetector
from ..pipe        import PIPEInterface


class ECP5SerDesPLLConfiguration:
    def __init__(self, refclk, refclk_freq, linerate):
        self.refclk = refclk
        self.config = self.compute_config(refclk_freq, linerate)

    @staticmethod
    def compute_config(refclk_freq, linerate):
        for mult in [8, 10, 16, 20, 25]:
            current_linerate = refclk_freq*mult
            if current_linerate == linerate:
                return {
                    "mult":       mult,
                    "refck_freq": refclk_freq,
                    "linerate":   linerate,
                }
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))



class ECP5SerDesConfigInterface(Elaboratable):
    """ Module that interfaces with the ECP5's SerDes Client Interface (SCI). """

    def __init__(self, serdes):
        self._serdes = serdes

        #
        # I/O port
        #

        # Control interface.
        self.dual_sel = Signal()
        self.chan_sel = Signal()
        self.re       = Signal()
        self.we       = Signal()
        self.done     = Signal()
        self.adr      = Signal(6)
        self.dat_w    = Signal(8)
        self.dat_r    = Signal(8)

        # SCI interface.
        self.sci_rd    = Signal()
        self.sci_wrn   = Signal()
        self.sci_addr  = Signal(6)
        self.sci_wdata = Signal(8)
        self.sci_rdata = Signal(8)



    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.sci_wrn.eq(1),

            self.sci_addr.eq(self.adr),
            self.sci_wdata.eq(self.dat_w)
        ]

        with m.FSM(domain="pipe"):

            with m.State("IDLE"):
                m.d.comb += self.done.eq(1)

                with m.If(self.we):
                    m.next = "WRITE"
                with m.Elif(self.re):
                    m.d.comb += self.sci_rd.eq(1),
                    m.next = "READ"

            with m.State("WRITE"):
                m.d.comb += self.sci_wrn.eq(0)
                m.next = "IDLE"


            with m.State("READ"):
                m.d.comb += self.sci_rd.eq(1)
                m.d.pipe += self.dat_r.eq(self.sci_rdata)
                m.next = "IDLE"

        return m


class ECP5SerDesRegisterTranslator(Elaboratable):
    """ Interface that converts control signals into SerDes register reads and writes. """

    def __init__(self, serdes, sci):
        self._serdes = serdes
        self._sci    = sci

        #
        # I/O port
        #
        self.loopback    = Signal()
        self.rx_polarity = Signal()
        self.tx_idle     = Signal()
        self.tx_polarity = Signal()
        self.rx_termination = Signal()


    def elaborate(self, platform):
        m = Module()
        sci = self._sci

        first = Signal()
        data  = Signal(8)


        with m.FSM(domain="pipe"):

            with m.State("IDLE"):
                m.d.pipe += first.eq(1)
                m.next = "READ-CH_01"

            with m.State("READ-CH_01"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.re.eq(1),
                    sci.adr.eq(0x01),
                ]

                with m.If(~first & sci.done):
                    m.d.comb += sci.re.eq(0)
                    m.d.pipe += [
                        data.eq(sci.dat_r),
                        first.eq(1)
                    ]
                    m.next = "WRITE-CH_01"


            with m.State("WRITE-CH_01"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.we.eq(1),
                    sci.adr.eq(0x01),
                    sci.dat_w.eq(data),
                    sci.dat_w[0].eq(self.rx_polarity),
                    sci.dat_w[1].eq(self.tx_polarity),
                ]
                with m.If(~first & sci.done):
                    m.d.comb += sci.we.eq(0)
                    m.d.pipe += first.eq(1)
                    m.next = "READ-CH_02"

            with m.State("READ-CH_02"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.re.eq(1),
                    sci.adr.eq(0x02),
                ]

                with m.If(~first & sci.done):
                    m.d.comb += sci.re.eq(0)
                    m.d.pipe += data.eq(sci.dat_r)
                    m.next = "WRITE-CH_02"

            with m.State("WRITE-CH_02"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.we.eq(1),
                    sci.adr.eq(0x02),
                    sci.dat_w.eq(data),
                    sci.dat_w[6].eq(self.tx_idle),  # pcie_ei_en
                ]

                with m.If(~first & sci.done):
                    m.d.pipe += first.eq(1)
                    m.d.comb += sci.we.eq(0)
                    m.next = "READ-CH_15"

            with m.State("READ-CH_15"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.re.eq(1),
                    sci.adr.eq(0x15),
                ]

                with m.If(~first & sci.done):
                    m.d.pipe += first.eq(1)
                    m.d.comb += sci.re.eq(0)
                    m.d.pipe += data.eq(sci.dat_r)
                    m.next = "WRITE-CH_15"

            with m.State("WRITE-CH_15"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.we.eq(1),
                    sci.adr.eq(0x15),
                    sci.dat_w.eq(data),
                ]
                with m.If(self.loopback):
                    m.d.comb += sci.dat_w[0:6].eq(0b110010) # lb_ctl

                with m.If(~first & sci.done):
                    m.d.comb += sci.we.eq(0)
                    m.next = "READ-CH_17"

            with m.State("READ-CH_17"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.re.eq(1),
                    sci.adr.eq(0x17),
                ]

                with m.If(~first & sci.done):
                    m.d.pipe += first.eq(1)
                    m.d.comb += sci.re.eq(0)
                    m.d.pipe += data.eq(sci.dat_r)
                    m.next = "WRITE-CH_17"

            with m.State("WRITE-CH_17"):
                m.d.pipe += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.we.eq(1),
                    sci.adr.eq(0x17),
                    sci.dat_w.eq(data),
                ]
                m.d.comb += sci.dat_w[0:5].eq(Mux(self.rx_termination, 22, 0))

                with m.If(~first & sci.done):
                    m.d.comb += sci.we.eq(0)
                    m.next = "IDLE"

        return m



class ECP5SerDesEqualizerInterface(Elaboratable):
    """ Interface that controls the ECP5 SerDes' equalization settings via SCI.

    Currently takes full ownership of the SerDes Client Interface.

    This unit allows runtime changing of the SerDes' equalizer settings.

    Attributes
    ----------
    enable_equalizer: Signal(), input
        Assert to enable the SerDes' equalizer.
    equalizer_pole: Signal(4), input
        Selects the pole used for the input equalization; ostensibly shifting the knee on the
        linear equalizer. The meaning of these values are not documented by Lattice.
    equalizer_level: Signal(2), input
        Selects the equalizer's gain. 0 = 6dB, 1 = 9dB, 2 = 12dB, 3 = undocumented.
        Note that the value `3` is marked as "not used" in the SerDes manual; but then used anyway
        by Lattice's reference designs.
    """

    SERDES_EQUALIZATION_REGISTER = 0x19

    def __init__(self, sci, serdes_channel):
        self._sci     = sci
        self._channel = serdes_channel

        #
        # I/O port
        #
        self.enable_equalizer = Signal()
        self.equalizer_pole   = Signal(4)
        self.equalizer_level  = Signal(2)


    def elaborate(self, platform):
        m = Module()
        sci = self._sci

        # Build the value to be written into the SCI equalizer register.
        m.d.comb += [
            sci.dat_w[0]    .eq(self.enable_equalizer),
            sci.dat_w[1:5]  .eq(self.equalizer_pole),
            sci.dat_w[5:7]  .eq(self.equalizer_level),

            # Set up a write to the equalizer control register.
            sci.chan_sel   .eq(self._channel),
            sci.we         .eq(1),
            sci.adr        .eq(self.SERDES_EQUALIZATION_REGISTER),
        ]

        return m




class ECP5SerDesEqualizer(Elaboratable):
    """ Interface that controls the ECP5 SerDes' equalization settings via SCI.

    Currently takes full ownership of the SerDes Client Interface.

    Ideally, an analog-informed receiver equalization would occur during USB3 link training. However,
    we're at best a simulacrum of a USB3 PHY built on an undocumented SerDes; so we'll do the best we
    can by measuring 8b10b encoding errors and trying various equalization settings until we've "minimized"
    bit error rate.

    Attributes
    ----------
    train_equalizer: Signal(), input
        When high, this unit attempts to train the Rx linear equalizer in order to minimize errors.
        This should be held only when a spectrally-rich data set is present, such as a training sequence.

    encoding_error_detected: Signal(), input
        Strobe; should be high each time the SerDes encounters an 8b10b encoding error.
    """

    # We'll try each equalizer setting for ~1024 cycles.
    # This value could easily be higher; but the higher this goes, the slower our counters
    # get; and we're operating in our fast, edge domain.
    CYCLES_PER_TRIAL = 127


    def __init__(self, sci, channel):
        self._sci     = sci
        self._channel = channel

        #
        # I/O port
        #
        self.train_equalizer         = Signal()
        self.encoding_error_detected = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Equalizer interface.
        #
        m.submodules.interface = interface = ECP5SerDesEqualizerInterface(
            sci=self._sci,
            serdes_channel=self._channel
        )

        #
        # Bit error counter.
        #
        clear_errors    = Signal()
        bit_errors_seen = Signal(range(self.CYCLES_PER_TRIAL + 1))

        with m.If(clear_errors):
            m.d.pipe += bit_errors_seen.eq(0)
        with m.Elif(self.encoding_error_detected):
            m.d.pipe += bit_errors_seen.eq(bit_errors_seen + 1)


        #
        # Naive equalization trainer.
        #

        # We'll use the naive-est possible algorithm: we'll try every setting and see what
        # minimizes bit error rate. This could definitely be improved upon, but without documentation
        # for the equalizer, we're best going for an exhaustive approach.

        # We'll track six bits, as we have four bits of pole and two bits of gain we want to try.
        current_settings = Signal(6)
        m.d.comb += [
            interface.enable_equalizer                                .eq(1),
            Cat(interface.equalizer_level, interface.equalizer_pole)  .eq(current_settings)
        ]

        # Keep track of the best equalizer setting seen thus far.
        best_equalizer_setting = Signal.like(current_settings)
        best_bit_error_count   = Signal.like(bit_errors_seen)

        # Keep track of how long we've been in this trial.
        cycles_spent_in_trial  = Signal(range(self.CYCLES_PER_TRIAL))


        # If we're actively training the equalizer...
        with m.If(self.train_equalizer):
            m.d.pipe += cycles_spent_in_trial.eq(cycles_spent_in_trial + 1)

            # If we're finishing a trial...
            with m.If(cycles_spent_in_trial == (self.CYCLES_PER_TRIAL - 1)):

                # ... clear our error count...
                m.d.comb += clear_errors.eq(1)

                # ... move to the next set of settings ...
                m.d.pipe += current_settings.eq(current_settings + 1)

                # ... and if this is a new best, store it.
                with m.If(bit_errors_seen < best_bit_error_count):
                    m.d.pipe += [
                        best_bit_error_count    .eq(bit_errors_seen),
                        best_equalizer_setting  .eq(current_settings)
                    ]

        # If we're not currently in training, always apply our known best settings.
        with m.Else():
            m.d.pipe += current_settings.eq(best_equalizer_setting)


        return m


class ECP5SerDesResetSequencer(Elaboratable):
    """ Reset sequencer; ensures that the PLL, CDR, and PCS all start correctly. """

    RESET_CYCLES  = 8
    RX_LOS_CYCLES = 4000
    RX_LOL_CYCLES = 62500
    RX_ERR_CYCLES = 1024

    def __init__(self):

        #
        # I/O port
        #

        # Reset in.
        self.reset          = Signal()

        # Status in.
        self.tx_pll_locked  = Signal()
        self.rx_has_signal  = Signal()
        self.rx_cdr_locked  = Signal()
        self.rx_coding_err  = Signal()

        # Reset out.
        self.tx_pll_reset   = Signal(reset=1)
        self.tx_pcs_reset   = Signal(reset=1)
        self.rx_cdr_reset   = Signal(reset=1)
        self.rx_pcs_reset   = Signal(reset=1)

        # Status out.
        self.tx_pcs_ready   = Signal()
        self.rx_pcs_ready   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Per [TN1261: "Reset Sequence"], the SerDes requires certain conditions to be met on start-up:
        # 1. The TxPLL must be locked before the CDR PLL reset is released.
        # 2. The PCS reset must be released only when the PLLs are locked.
        #
        # Per [Lattice FAQ 697], if the PCS is not held in reset and the Rx recovered clock is unstable,
        # the PCS FIFO pointers may get corrupted. In this case, there will be no 8b10b code violations
        # or disparity errors indicated, and the Rx link state machine will indicate synchronization
        # to the Rx bitstream, but the PCS may return corrupt data.
        #
        # Per [FPGA-PB-02001], the Rx CDR and PCS require a cascaded reset sequence for reliable operation.
        # On loss of signal, the Rx CDR and PCS are reset; and on loss of lock, the Rx PCS is reset.


        # Synchronize status signals to our clock.
        tx_pll_locked = Signal()
        rx_has_signal = Signal()
        rx_cdr_locked = Signal()
        rx_coding_err = Signal()
        m.submodules += [
            FFSynchronizer(self.tx_pll_locked, tx_pll_locked, o_domain="ss"),
            FFSynchronizer(self.rx_has_signal, rx_has_signal, o_domain="ss"),
            FFSynchronizer(self.rx_cdr_locked, rx_cdr_locked, o_domain="ss"),
            FFSynchronizer(self.rx_coding_err, rx_coding_err, o_domain="ss"),
        ]


        def apply_resets(m, tx_pll, tx_pcs, rx_cdr, rx_pcs):
            # The SerDes reset inputs are asynchronous; register our outputs so they do not have glitches.
            m.d.ss += [
                self.tx_pll_reset.eq(tx_pll),
                self.tx_pcs_reset.eq(tx_pcs),
                self.rx_cdr_reset.eq(rx_cdr),
                self.rx_pcs_reset.eq(rx_pcs),
            ]

        def apply_readys(m, tx_pcs, rx_pcs):
            m.d.ss += [
                self.tx_pcs_ready.eq(tx_pcs),
                self.rx_pcs_ready.eq(rx_pcs),
            ]


        timer = Signal(range(max(self.RESET_CYCLES, self.RX_LOS_CYCLES, self.RX_LOL_CYCLES)))

        with m.FSM(domain="ss"):

            # Hold everything in reset, initially.
            with m.State("INITIAL_RESET"):
                apply_resets(m, tx_pll=1, tx_pcs=1, rx_cdr=1, rx_pcs=1)
                apply_readys(m, tx_pcs=0, rx_pcs=0)

                m.next = "WAIT_FOR_TXPLL_LOCK"

            # Deassert Tx PLL reset, and wait for it to start up.
            with m.State("WAIT_FOR_TXPLL_LOCK"):
                apply_resets(m, tx_pll=0, tx_pcs=1, rx_cdr=1, rx_pcs=1)
                apply_readys(m, tx_pcs=0, rx_pcs=0)

                with m.If(tx_pll_locked):
                    m.d.ss += timer.eq(0)
                    m.next = "APPLY_TXPCS_RESET"

            # Reset Tx PCS.
            with m.State("APPLY_TXPCS_RESET"):
                apply_resets(m, tx_pll=0, tx_pcs=1, rx_cdr=1, rx_pcs=1)
                apply_readys(m, tx_pcs=0, rx_pcs=0)

                with m.If(timer + 1 != self.RESET_CYCLES):
                    m.d.ss += timer.eq(timer + 1)
                with m.Else():
                    m.d.ss += timer.eq(0)
                    m.next = "WAIT_FOR_RX_SIGNAL"

            # Deassert Tx PCS reset, and wait until Rx signal is present.
            with m.State("WAIT_FOR_RX_SIGNAL"):
                # CDR reset implies LOS reset; and must be deasserted for LOS to go low.
                # This is not documented in [TN1261], and contradicts [FPGA-PB-02001].
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=0, rx_pcs=1)
                apply_readys(m, tx_pcs=1, rx_pcs=0)

                with m.If(~rx_has_signal):
                    m.d.ss += timer.eq(0)
                with m.Else():
                    with m.If(timer + 1 != self.RX_LOS_CYCLES):
                        m.d.ss += timer.eq(timer + 1)
                    with m.Else():
                        m.d.ss += timer.eq(0)
                        m.next = "APPLY_CDR_RESET"

                with m.If(~tx_pll_locked):
                    m.next = "WAIT_FOR_TXPLL_LOCK"

            # Reset CDR.
            with m.State("APPLY_CDR_RESET"):
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=1, rx_pcs=1)
                apply_readys(m, tx_pcs=1, rx_pcs=0)

                with m.If(timer + 1 != self.RESET_CYCLES):
                    m.d.ss += timer.eq(timer + 1)
                with m.Else():
                    m.d.ss += timer.eq(0)
                    m.next = "DELAY_FOR_CDR_LOCK"

            # Deassert CDR reset, and wait until CDR had some time to lock (to embedded Rx clock).
            with m.State("DELAY_FOR_CDR_LOCK"):
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=0, rx_pcs=1)
                apply_readys(m, tx_pcs=1, rx_pcs=0)

                with m.If(timer + 1 != self.RX_LOL_CYCLES):
                    m.d.ss += timer.eq(timer + 1)
                with m.Else():
                    m.d.ss += timer.eq(0)
                    m.next = "CHECK_FOR_CDR_LOCK"

                with m.If(~rx_has_signal):
                    m.next = "WAIT_FOR_RX_SIGNAL"
                with m.If(~tx_pll_locked):
                    m.next = "WAIT_FOR_TXPLL_LOCK"

            # Wait until CDR has been locked for a while; and if it lost lock, reset it.
            with m.State("CHECK_FOR_CDR_LOCK"):
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=0, rx_pcs=1)
                apply_readys(m, tx_pcs=1, rx_pcs=0)

                with m.If(~rx_cdr_locked):
                    m.d.ss += timer.eq(0)
                    m.next = "APPLY_CDR_RESET"
                with m.Else():
                    with m.If(timer + 1 != self.RX_LOL_CYCLES):
                        m.d.ss += timer.eq(timer + 1)
                    with m.Else():
                        m.d.ss += timer.eq(0)
                        m.next = "APPLY_RXPCS_RESET"

                with m.If(~rx_has_signal):
                    m.next = "WAIT_FOR_RX_SIGNAL"
                with m.If(~tx_pll_locked):
                    m.next = "WAIT_FOR_TXPLL_LOCK"

            # Reset Rx PCS.
            with m.State("APPLY_RXPCS_RESET"):
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=0, rx_pcs=1)
                apply_readys(m, tx_pcs=1, rx_pcs=0)

                with m.If(timer + 1 != self.RESET_CYCLES):
                    m.d.ss += timer.eq(timer + 1)
                with m.Else():
                    m.d.ss += timer.eq(0)
                    m.next = "DELAY_FOR_RXPCS_LOCK"

            # Deassert Rx PCS reset, and wait until PCS had some time to lock (to a K28.5 comma).
            with m.State("DELAY_FOR_RXPCS_LOCK"):
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=0, rx_pcs=0)
                apply_readys(m, tx_pcs=1, rx_pcs=0)

                with m.If(timer + 1 != self.RX_ERR_CYCLES):
                    m.d.ss += timer.eq(timer + 1)
                with m.Else():
                    m.d.ss += timer.eq(0)
                    m.next = "CHECK_FOR_RXPCS_LOCK"

                with m.If(~rx_has_signal):
                    m.next = "WAIT_FOR_RX_SIGNAL"
                with m.If(~tx_pll_locked):
                    m.next = "WAIT_FOR_TXPLL_LOCK"

            # Wait until Rx PCS has been locked for a while; and if it lost lock, reset it.
            with m.State("CHECK_FOR_RXPCS_LOCK"):
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=0, rx_pcs=0)
                apply_readys(m, tx_pcs=1, rx_pcs=0)

                with m.If(rx_coding_err):
                    m.d.ss += timer.eq(0)
                    m.next = "APPLY_RXPCS_RESET"
                with m.Else():
                    with m.If(timer + 1 != self.RX_ERR_CYCLES):
                        m.d.ss += timer.eq(timer + 1)
                    with m.Else():
                        m.d.ss += timer.eq(0)
                        m.next = "IDLE"

                with m.If(~rx_has_signal):
                    m.next = "WAIT_FOR_RX_SIGNAL"
                with m.If(~tx_pll_locked):
                    m.next = "WAIT_FOR_TXPLL_LOCK"

            # Everything is okay; monitor for errors, and restart the reset sequence if necessary.
            with m.State("IDLE"):
                apply_resets(m, tx_pll=0, tx_pcs=0, rx_cdr=0, rx_pcs=0)
                apply_readys(m, tx_pcs=1, rx_pcs=1)

                with m.If(rx_coding_err):
                    m.next = "APPLY_RXPCS_RESET"
                with m.If(~rx_has_signal):
                    m.next = "WAIT_FOR_RX_SIGNAL"
                with m.If(~tx_pll_locked):
                    m.next = "WAIT_FOR_TXPLL_LOCK"

        return ResetInserter({"ss": self.reset})(m)


class ECP5SerDes(Elaboratable):
    """ Abstraction layer for working with the ECP5 SerDes. """

    def __init__(self, pll_config, tx_pads, rx_pads, dual=0, channel=0):
        assert dual    in [0, 1]
        assert channel in [0, 1]

        self._pll           = pll_config
        self._tx_pads       = tx_pads
        self._rx_pads       = rx_pads
        self._dual          = dual
        self._channel       = channel

        # Since we run at the 5 GT/s data rate, we always operate with 2x gearing;
        # the ECP5 fabric is not fast enough to process this much data otherwise.
        self._io_words      = 2

        #
        # I/O ports.
        #

        # Interface clock.
        self.pclk           = Signal()

        # Reset sequencing.
        self.reset          = Signal()
        self.tx_ready       = Signal()
        self.rx_ready       = Signal()

        # Core Rx and Tx lines.
        self.tx_data        = Signal(self._io_words * 8)
        self.tx_datak       = Signal(self._io_words)
        self.rx_data        = Signal(self._io_words * 8)
        self.rx_datak       = Signal(self._io_words)

        # TX controls
        self.tx_polarity    = Signal()
        self.tx_elec_idle   = Signal()
        self.tx_gpio_en     = Signal()
        self.tx_gpio        = Signal()

        # RX controls
        self.rx_polarity    = Signal()
        self.rx_gpio        = Signal()
        self.rx_termination = Signal()

        # RX status
        self.rx_status      = Signal(3)


    def elaborate(self, platform):
        m = Module()


        # Internal signals.
        tx_clk_full = Signal()
        tx_clk_half = Signal()

        tx_lol      = Signal()
        tx_bus      = Signal(24)

        rx_los      = Signal()
        rx_lol      = Signal()
        rx_err      = Signal()
        rx_ctc_urun = Signal()
        rx_ctc_orun = Signal()
        rx_align    = Signal()
        rx_bus      = Signal(24)


        #
        # Clocking / reset control.
        #

        # The SerDes needs to be brought up gradually; we'll do that here.
        m.submodules.reset_sequencer = reset = ECP5SerDesResetSequencer()
        m.d.comb += [
            reset.reset         .eq(self.reset),
            reset.tx_pll_locked .eq(~tx_lol),
            reset.rx_has_signal .eq(~rx_los),
            reset.rx_cdr_locked .eq(~rx_lol),
            reset.rx_coding_err .eq(rx_err),
            self.tx_ready       .eq(reset.tx_pcs_ready),
            self.rx_ready       .eq(reset.rx_pcs_ready),
        ]

        # Generate the PIPE interface clock from the half rate transmit byte clock, and use it to drive
        # both the Tx and the Rx FIFOs, to bring both halves of the data bus to the same clock domain.
        # The recovered Rx clock will not match the generated Tx clock; use the full rate transmit byte
        # clock to drive the CTC FIFO in the SerDes, which will compensate for the difference.
        m.d.comb += [
            self.pclk           .eq(tx_clk_half),
        ]


        #
        # SerDes parameter control.
        #

        # Some of the SerDes parameters cannot be directly controlled with fabric signals, but have to
        # be configured through the SerDes client interface.
        m.submodules.sci = sci = ECP5SerDesConfigInterface(self)
        m.submodules.sci_trans = sci_trans = ECP5SerDesRegisterTranslator(self, sci)
        m.d.comb += [
            sci_trans.tx_polarity   .eq(self.tx_polarity),
            sci_trans.rx_polarity   .eq(self.rx_polarity),
            sci_trans.rx_termination.eq(self.rx_termination),
        ]


        #
        # Core SerDes instantiation.
        #
        serdes_params = dict(
            # Note that Lattice Diamond needs these parameters in their provided bases (and string lengths!).
            # Changing their bases will work with the open toolchain, but will make Diamond mad.

            # DCU — power management
            p_D_MACROPDB            = "0b1",
            p_D_IB_PWDNB            = "0b1",
            p_D_TXPLL_PWDNB         = "0b1",
            i_D_FFC_MACROPDB        = 1,

            # DCU — reset
            i_D_FFC_MACRO_RST       = self.reset,
            i_D_FFC_DUAL_RST        = self.reset,

            # DCU — clocking
            i_D_REFCLKI             = self._pll.refclk,
            o_D_FFS_PLOL            = tx_lol,
            p_D_REFCK_MODE          = {
                25: "0b100",
                20: "0b000",
                16: "0b010",
                10: "0b001",
                 8: "0b011"}[self._pll.config["mult"]],
            p_D_TX_MAX_RATE         = "5.0",    # 5.0 Gbps
            p_D_TX_VCO_CK_DIV       = {
                32: "0b111",
                16: "0b110",
                 8: "0b101",
                 4: "0b100",
                 2: "0b010",
                 1: "0b000"}[1],                # DIV/1
            p_D_BITCLK_LOCAL_EN     = "0b1",    # Use clock from local PLL

            # DCU — clock multiplier unit
            # begin undocumented (Clarity Designer values for 5 Gbps PCIe used)
            p_D_CMUSETBIASI         = "0b00",
            p_D_CMUSETI4CPP         = "0d4",
            p_D_CMUSETI4CPZ         = "0d3",
            p_D_CMUSETI4VCO         = "0b00",
            p_D_CMUSETICP4P         = "0b01",
            p_D_CMUSETICP4Z         = "0b101",
            p_D_CMUSETINITVCT       = "0b00",
            p_D_CMUSETISCL4VCO      = "0b000",
            p_D_CMUSETP1GM          = "0b000",
            p_D_CMUSETP2AGM         = "0b000",
            p_D_CMUSETZGM           = "0b100",
            # end undocumented

            # DCU — unknown
            # begin undocumented (Clarity Designer values for 5 Gbps PCIe used)
            p_D_PD_ISET             = "0b11",
            p_D_RG_EN               = "0b0",
            p_D_RG_SET              = "0b00",
            p_D_SETICONST_AUX       = "0b01",
            p_D_SETICONST_CH        = "0b10",
            p_D_SETIRPOLY_AUX       = "0b10",
            p_D_SETIRPOLY_CH        = "0b10",
            p_D_SETPLLRC            = "0d1",
            # end undocumented

            # CHX common ---------------------------------------------------------------------------
            # CHX — protocol
            p_CHX_PROTOCOL          = "G8B10B",
            p_CHX_PCIE_MODE         = "0b1",

            p_CHX_ENC_BYPASS        = "0b0",    # Use the 8b10b encoder
            p_CHX_DEC_BYPASS        = "0b0",    # Use the 8b10b decoder

            # CHX receive --------------------------------------------------------------------------
            # CHX RX — power management
            p_CHX_RPWDNB            = "0b1",
            i_CHX_FFC_RXPWDNB       = 1,

            # CHX RX — reset
            i_CHX_FFC_RRST          = reset.rx_cdr_reset,
            i_CHX_FFC_LANE_RX_RST   = reset.rx_pcs_reset | rx_ctc_urun | rx_ctc_orun,

            # CHX RX — input
            i_CHX_HDINP             = self._rx_pads.p,
            i_CHX_HDINN             = self._rx_pads.n,

            p_CHX_LDR_RX2CORE_SEL   = "0b1",            # Enables low-speed out-of-band input.
            o_CHX_LDR_RX2CORE       = self.rx_gpio,

            p_CHX_RTERM_RX          = {
                "5k-ohms":        "0d0",
                "80-ohms":        "0d1",
                "75-ohms":        "0d4",
                "70-ohms":        "0d6",
                "60-ohms":        "0d11",
                "50-ohms":        "0d19",
                "46-ohms":        "0d25",
                "wizard-50-ohms": "0d22"}["5k-ohms"], # Set via SCI
            p_CHX_RXTERM_CM         = "0b10",   # Terminate RX to GND
            p_CHX_RXIN_CM           = "0b11",   # Common mode feedback

            # CHX RX — equalizer
            p_D_REQ_ISET            = "0b011",  # Undocumented, needs to be 010 or 011
            p_CHX_REQ_EN            = "0b1",    # Enable equalizer
            p_CHX_REQ_LVL_SET       = "0b01",   # Equalizer attenuation, 9 dB
            p_CHX_RX_RATE_SEL       = "0d09",   # Equalizer pole position, values documented as "TBD"

            # CHX RX — clocking
            p_CHX_FF_RX_H_CLK_EN    = "0b0",    # disable DIV/2 output clock
            p_CHX_FF_RX_F_CLK_DIS   = "0b1",    # disable DIV/1 output clock
            p_CHX_SEL_SD_RX_CLK     = "0b0",    # FIFO write driven by CTC buffer read clock
            i_CHX_FF_EBRD_CLK       = tx_clk_full,
            p_CHX_RX_GEAR_MODE      = "0b1",    # 1:2 gearbox
            i_CHX_FF_RXI_CLK        = tx_clk_half,

            # CHX RX — clock and data recovery
            p_CHX_CDR_MAX_RATE      = "5.0",    # 5.0 Gbps
            i_CHX_RX_REFCLK         = self._pll.refclk,
            p_CHX_RX_DCO_CK_DIV     = {
                32: "0b111",
                16: "0b110",
                 8: "0b101",
                 4: "0b100",
                 2: "0b010",
                 1: "0b000"}[1],                # DIV/1

            # begin undocumented (Clarity Designer values for 5 Gbps PCIe used)
            p_CHX_DCOATDCFG         = "0b00",
            p_CHX_DCOATDDLY         = "0b00",
            p_CHX_DCOBYPSATD        = "0b1",
            p_CHX_DCOCALDIV         = "0b010",
            p_CHX_DCOCTLGI          = "0b011",
            p_CHX_DCODISBDAVOID     = "0b1",
            p_CHX_DCOFLTDAC         = "0b00",
            p_CHX_DCOFTNRG          = "0b001",
            p_CHX_DCOIOSTUNE        = "0b010",
            p_CHX_DCOITUNE          = "0b00",
            p_CHX_DCOITUNE4LSB      = "0b010",
            p_CHX_DCOIUPDNX2        = "0b1",
            p_CHX_DCONUOFLSB        = "0b101",
            p_CHX_DCOSCALEI         = "0b01",
            p_CHX_DCOSTARTVAL       = "0b010",
            p_CHX_DCOSTEP           = "0b11",
            p_CHX_BAND_THRESHOLD    = "0d0",
            p_CHX_AUTO_FACQ_EN      = "0b1",
            p_CHX_AUTO_CALIB_EN     = "0b1",
            p_CHX_CALIB_CK_MODE     = "0b1",
            p_D_DCO_CALIB_TIME_SEL  = "0b00",
            p_CHX_REG_BAND_OFFSET   = "0d0",
            p_CHX_REG_BAND_SEL      = "0d0",
            p_CHX_REG_IDAC_SEL      = "0d0",
            p_CHX_REG_IDAC_EN       = "0b0",
            # end undocumented

            # CHX RX — loss of signal
            # Undocumented values were taken from Clarity Designer output for 5 Gbps PCIe
            o_CHX_FFS_RLOS          = rx_los,
            p_CHX_RLOS_SEL          = "0b1",
            p_CHX_RX_LOS_EN         = "0b1",
            p_CHX_RX_LOS_LVL        = "0b100",  # Values documented as "TBD"
            p_CHX_RX_LOS_CEQ        = "0b11",   # Values documented as "TBD"
            p_CHX_RX_LOS_HYST_EN    = "0b0",
            p_CHX_PDEN_SEL          = "0b1",    # phase detector disabled on LOS

            # CHX RX — loss of lock
            o_CHX_FFS_RLOL          = rx_lol,
            # USB requires the use of spread spectrum clocking, modulating the frequency from
            # +0 to -5000 ppm of the base 5 GHz clock.
            p_D_CDR_LOL_SET         = "0b10",   # ±4000 ppm lock, ±7000 ppm unlock

            # CHX RX — comma alignment
            # In the User Configured mode (generic 8b10b), the link state machine must be disabled
            # using CHx_LSM_DISABLE, or the CHx_FFC_ENABLE_CGALIGN and CHx_FFC_CR_EN_BITSLIP inputs
            # will not affect the WA and CDR.
            p_CHX_LSM_DISABLE       = "0b1",
            # The CHx_FFC_ENABLE_CGALIGN input is edge-sensitive; a posedge enables the word aligner,
            # which, once it discovers a comma, configures the barrel shifter and disables itself.
            # A constant level on this input does not affect WA; neither does the CHx_ENABLE_CG_ALIGN
            # parameter.
            i_CHX_FFC_ENABLE_CGALIGN= rx_err,

            p_CHX_UDF_COMMA_MASK    = "0x3ff",  # compare all bits
            p_CHX_UDF_COMMA_A       = "0x17c",   # 0b0101_111100, K28.5 RD- 10b code
            p_CHX_UDF_COMMA_B       = "0x283",   # 0b1010_000011, K28.5 RD+ 10b code

            # CHX RX — clock tolerance compensation
            # Due to spread spectrum modulation, the USB 3 word clock is, on average, 2.5% slower
            # than the base 5 GHz line rate. Since the USB soft logic always runs at a fraction of
            # the base line rate, SKP ordered sets only need to be removed, and RX FIFO underrun
            # can be handled using clock enables alone.
            p_CHX_CTC_BYPASS        = "0b0",    # enable CTC FIFO
            p_CHX_MIN_IPG_CNT       = "0b00",   # minimum interpacket gap of 1X (multiplied by match length)
            p_CHX_MATCH_2_ENABLE    = "0b1",    # enable  2 character skip matching (using characters 3..4)
            p_CHX_MATCH_4_ENABLE    = "0b0",    # disable 4 character skip matching (using characters 1..4)
            p_CHX_CC_MATCH_1        = "0x13c",   # K28.1 1+8b code
            p_CHX_CC_MATCH_2        = "0x13c",   # K28.1 1+8b code
            p_CHX_CC_MATCH_3        = "0x13c",   # K28.1 1+8b code
            p_CHX_CC_MATCH_4        = "0x13c",   # K28.1 1+8b code
            p_D_LOW_MARK            = "0d4",    # CTC FIFO low  water mark (mean=8)
            p_D_HIGH_MARK           = "0d12",   # CTC FIFO high water mark (mean=8)

            # The CTC FIFO underrun and overrun flags are 'sticky'; once the condition occurs, the flag
            # remains set until the RX PCS is reset. This affects the PIPE RxStatus output as well; to
            # be PIPE-compliant, reset the PCS immediately on overrun/underrun.
            o_CHX_FFS_CC_UNDERRUN   = rx_ctc_urun,
            o_CHX_FFS_CC_OVERRUN    = rx_ctc_orun,

            # CHX RX — data
            **{"o_CHX_FF_RX_D_%d" % n: rx_bus[n] for n in range(len(rx_bus))},

            # CHX transmit -------------------------------------------------------------------------
            # CHX TX — power management
            p_CHX_TPWDNB            = "0b1",
            i_CHX_FFC_TXPWDNB       = 1,

            # CHX TX — reset
            i_D_FFC_TRST            = reset.tx_pll_reset,
            i_CHX_FFC_LANE_TX_RST   = reset.tx_pcs_reset,

            # CHX TX — output
            o_CHX_HDOUTP            = self._tx_pads.p,
            o_CHX_HDOUTN            = self._tx_pads.n,

            p_CHX_LDR_CORE2TX_SEL   = "0b0",            # Uses CORE2TX_EN to enable out-of-band output.
            i_CHX_LDR_CORE2TX       = self.tx_gpio,
            i_CHX_FFC_LDR_CORE2TX_EN= self.tx_gpio_en,

            p_CHX_RTERM_TX          = {
                "5k-ohms":        "0d0",
                "80-ohms":        "0d1",
                "75-ohms":        "0d4",
                "70-ohms":        "0d6",
                "60-ohms":        "0d11",
                "50-ohms":        "0d19",
                "46-ohms":        "0d25",
                "wizard-50-ohms": "0d19"}["50-ohms"],
            p_CHX_TXAMPLITUDE       = "0d1000", # 1000 mV

            # CHX TX — equalization
            p_CHX_TDRV_SLICE0_CUR   = "0b011",  # 400 uA
            p_CHX_TDRV_SLICE0_SEL   = "0b01",   # main data
            p_CHX_TDRV_SLICE1_CUR   = "0b000",  # 100 uA
            p_CHX_TDRV_SLICE1_SEL   = "0b00",   # power down
            p_CHX_TDRV_SLICE2_CUR   = "0b11",   # 3200 uA
            p_CHX_TDRV_SLICE2_SEL   = "0b01",   # main data
            p_CHX_TDRV_SLICE3_CUR   = "0b10",   # 2400 uA
            p_CHX_TDRV_SLICE3_SEL   = "0b01",   # main data
            p_CHX_TDRV_SLICE4_CUR   = "0b00",   # 800 uA
            p_CHX_TDRV_SLICE4_SEL   = "0b00",   # power down
            p_CHX_TDRV_SLICE5_CUR   = "0b00",   # 800 uA
            p_CHX_TDRV_SLICE5_SEL   = "0b00",   # power down

            # CHX TX — clocking
            p_CHX_FF_TX_F_CLK_DIS   = "0b0",    # enable  DIV/1 output clock
            o_CHX_FF_TX_F_CLK       = tx_clk_full,
            p_CHX_FF_TX_H_CLK_EN    = "0b1",    # enable  DIV/2 output clock
            o_CHX_FF_TX_PCLK        = tx_clk_half, # ff_tx_pclk feeds a pclk net, ff_tx_h_clk does not
            p_CHX_TX_GEAR_MODE      = "0b1",    # 1:2 gearbox
            i_CHX_FF_TXI_CLK        = tx_clk_half,

            # CHX TX — data
            **{"i_CHX_FF_TX_D_%d" % n: tx_bus[n] for n in range(len(tx_bus))},

            i_CHX_FFC_EI_EN         = self.tx_elec_idle & ~self.tx_gpio_en,

            # SCI interface ------------------------------------------------------------------------
            **{"i_D_SCIWDATA%d" % n: sci.sci_wdata[n] for n in range(8)},
            **{"i_D_SCIADDR%d"  % n: sci.sci_addr [n] for n in range(6)},
            **{"o_D_SCIRDATA%d" % n: sci.sci_rdata[n] for n in range(8)},
            i_D_SCIENAUX  = sci.dual_sel,
            i_D_SCISELAUX = sci.dual_sel,
            i_CHX_SCIEN   = sci.chan_sel,
            i_CHX_SCISEL  = sci.chan_sel,
            i_D_SCIRD     = sci.sci_rd,
            i_D_SCIWSTN   = sci.sci_wrn,
        )

        # Translate the 'CHX' string to the correct channel name in each of our SerDes parameters,
        # and create our SerDes instance.
        serdes_params = {k.replace("CHX", f"CH{self._channel}"):v for (k,v) in serdes_params.items()}
        m.submodules.serdes = serdes = Instance("DCUA", **serdes_params)

        # Bind our SerDes to the correct location inside the FPGA.
        serdes.attrs["LOC"] = "DCU{}".format(self._dual)
        serdes.attrs["CHAN"] = "CH{}".format(self._channel)

        # SerDes decodes invalid 10b symbols to 0xEE with control bit set, which is not a part
        # of the 8b10b encoding space. We use it to drive the comma aligner and reset sequencer.
        # This signal is registered so that it can be sampled from asynchronous domains.
        m.d.pipe += [
            rx_err.eq(rx_bus[8]  & (rx_bus[ 0: 8] == 0xee) |
                      rx_bus[20] & (rx_bus[12:20] == 0xee)),
        ]

        #
        # TX and RX datapaths
        #
        rx_status = [Signal(3) for _ in range(self._io_words)]

        m.d.comb += [
            # Grab our received data directly from our SerDes; modifying things to match the
            # SerDes Rx bus layout, which squishes status signals between our two geared words.
            self.rx_data[0: 8]  .eq(rx_bus[ 0: 8]),
            self.rx_data[8:16]  .eq(rx_bus[12:20]),
            self.rx_datak[0]    .eq(rx_bus[8]),
            self.rx_datak[1]    .eq(rx_bus[20]),
            rx_status[0]        .eq(rx_bus[ 9:12]),
            rx_status[1]        .eq(rx_bus[21:24]),

            # Stick the data we'd like to transmit into the SerDes; again modifying things to match
            # the transmit bus layout.
            tx_bus[ 0: 8]       .eq(self.tx_data[0: 8]),
            tx_bus[12:20]       .eq(self.tx_data[8:16]),
            tx_bus[8]           .eq(self.tx_datak[0]),
            tx_bus[20]          .eq(self.tx_datak[1]),
        ]

        # The SerDes is providing us with two RxStatus words, one per byte; but we emit only one
        # for the entire word. Combine the status conditions together according to their priorities.
        for rx_status_code in 0b011, 0b010, 0b001, 0b111, 0b110, 0b101, 0b100:
            with m.If(Cat(rx_status[i] == rx_status_code for i in range(self._io_words)).any()):
                m.d.comb += self.rx_status.eq(rx_status_code)


        return m


class ECP5SerDesPIPE(PIPEInterface, Elaboratable):
    """ Wrapper around the core ECP5 SerDes that adapts it to the PIPE interface.

    The implementation-dependent behavior of the standard PIPE signals is described below:

    width :
        Interface width. Always 2 symbols.
    clk :
        Reference clock for the PHY receiver and transmitter. Could be routed through fabric,
        or connected to the output of an ``EXTREFB`` block. Frequency must be one of 250 MHz,
        200 MHz, or 312.5 MHz.
    pclk :
        Clock for the PHY interface. Frequency is always 250 MHz.
    phy_mode :
        PHY operating mode. Only SuperSpeed USB mode is supported.
    elas_buf_mode :
        Elastic buffer mode. Only nominal half-full mode is supported.
    rate :
        Link signaling rate. Only 5 GT/s is supported.
    power_down :
        Power management mode. Only P0 is supported.
    tx_deemph :
        Transmitter de-emphasis level. Only TBD is supported.
    tx_margin :
        Transmitter voltage levels. Only TBD is supported.
    tx_swing :
        Transmitter voltage swing level. Only full swing is supported.
    tx_detrx_lpbk :
    tx_elec_idle :
        Transmit control signals. Loopback and receiver detection are not implemented.
    tx_compliance :
    tx_ones_zeroes :
    rx_eq_training :
        These inputs are not implemented.
    power_present :
        This output is not implemented. External logic may drive it if necessary.
    """

    def __init__(self, *, tx_pads, rx_pads, channel=0, dual=0, refclk_frequency):
        super().__init__(width=2)

        self._tx_pads                 = tx_pads
        self._rx_pads                 = rx_pads
        self._channel                 = channel
        self._dual                    = dual
        self._refclk_frequency        = refclk_frequency


    def elaborate(self, platform):
        m = Module()

        #
        # SerDes instantiation.
        #
        pll_config = ECP5SerDesPLLConfiguration(
            refclk      = self.clk,
            refclk_freq = self._refclk_frequency,
            linerate    = 5e9
        )
        m.submodules.serdes = serdes = ECP5SerDes(
            pll_config  = pll_config,
            tx_pads     = self._tx_pads,
            rx_pads     = self._rx_pads,
            channel     = self._channel,
        )

        # Our soft PHY includes some logic that needs to run synchronously to the PIPE clock; create
        # a local clock domain to drive it.
        m.domains.pipe = ClockDomain(local=True, async_reset=True)
        m.d.comb += [
            ClockSignal("pipe")     .eq(serdes.pclk),
        ]


        #
        # LFPS generation & detection.
        #
        m.submodules.lfps_generator = lfps_generator = LFPSSquareWaveGenerator(25e6, 250e6)
        m.submodules.lfps_detector  = lfps_detector  = LFPSSquareWaveDetector(250e6)
        m.d.comb += [
            serdes.tx_gpio_en       .eq(lfps_generator.tx_gpio_en),
            serdes.tx_gpio          .eq(lfps_generator.tx_gpio),
            lfps_detector.rx_gpio   .eq(serdes.rx_gpio),
        ]


        #
        # PIPE interface signaling.
        #
        m.d.comb += [
            serdes.reset            .eq(self.reset),
            self.pclk               .eq(serdes.pclk),

            serdes.tx_elec_idle     .eq(self.tx_elec_idle),
            serdes.rx_polarity      .eq(self.rx_polarity),
            serdes.rx_termination   .eq(self.rx_termination),
            lfps_generator.generate .eq(self.tx_detrx_lpbk & self.tx_elec_idle),

            self.phy_status         .eq(~serdes.tx_ready),
            self.rx_valid           .eq(serdes.rx_ready),
            self.rx_status          .eq(serdes.rx_status),
            self.rx_elec_idle       .eq(~lfps_detector.present),

            serdes.tx_data          .eq(self.tx_data),
            serdes.tx_datak         .eq(self.tx_datak),
            self.rx_data            .eq(serdes.rx_data),
            self.rx_datak           .eq(serdes.rx_datak),
        ]

        return m
