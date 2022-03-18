#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based in part on ``litex`` and ``liteiclink``.
# SPDX-License-Identifier: BSD-3-Clause
""" SerDes backend for the Artix7. """

from amaranth import *
from amaranth.lib.cdc import FFSynchronizer, ResetSynchronizer


from .soft                        import Encoder
from ..datapath                   import ReceivePostprocessing, TransmitPreprocessing
from ..lfps                       import LFPSSquareWaveGenerator

from ....usb.stream               import USBRawSuperSpeedStream
from ....usb.usb3.physical.coding import *


class WaitTimer(Elaboratable):
    def __init__(self, t):
        self._t   = t
        self.wait = Signal()
        self.done = Signal()


    def elaborate(self, platform):
        m = Module()

        count = Signal(range(self._t + 1), reset=self._t)
        m.d.comb += self.done.eq(count == 0)

        with m.If(self.wait):
            with m.If(~self.done):
                m.d.ss += count.eq(count + 1)
        with m.Else():
            m.d.ss += count.eq(count.reset)

        return m


class DRPInterface:
    def __init__(self):
        self.lock = Signal()
        self.addr = Signal(9)
        self.di   = Signal(16)
        self.do   = Signal(16)
        self.we   = Signal(1)
        self.en   = Signal(1)
        self.rdy  = Signal(1)


class DRPInterfaceBuffer(Elaboratable):
    def __init__(self, interface):
        self.intf = interface

        self.addr_latch = Signal.like(interface.addr)
        self.di_latch = Signal.like(interface.di)
        self.we_latch = Signal.like(interface.we)
        self.en_latch = Signal.like(interface.en)


    def elaborate(self, platform):
        m = Module()

        with m.If(self.intf.en):
            m.d.ss += [
                self.addr_latch.eq(self.intf.addr),
                self.di_latch.eq(self.intf.di),
                self.we_latch.eq(self.intf.we),
                self.en_latch.eq(1),
            ]

        with m.Elif(self.intf.rdy):
            m.d.ss += [
                self.en_latch.eq(0),
            ]

        return m


class DRPArbiter(Elaboratable):
    def __init__(self):
        self.shared = DRPInterface()
        self.interfaces = []

    def add_interface(self, interface):
        self.interfaces.append(interface)

    def elaborate(self, platform):
        m = Module()

        buffers = Array(DRPInterfaceBuffer(intf) for intf in self.interfaces)
        m.submodules += buffers

        current_idx = Signal(range(len(buffers)))
        current_buf = buffers[current_idx]

        with m.FSM(domain="ss"):

            with m.State("IDLE"):
                for idx in range(len(buffers)):
                    with m.If(buffers[idx].en_latch):
                        m.d.ss += current_idx.eq(idx)
                        m.next = "REQUEST"

            with m.State("REQUEST"):
                m.d.comb += [
                    self.shared.addr.eq(current_buf.addr_latch),
                    self.shared.di.eq(current_buf.di_latch),
                    self.shared.we.eq(current_buf.we_latch),
                    self.shared.en.eq(current_buf.en_latch),
                ]
                with m.If(self.shared.en):
                    m.next = "REPLY"
                with m.Elif(~current_buf.intf.lock):
                    m.next = "IDLE"

            with m.State("REPLY"):
                m.d.comb += [
                    current_buf.intf.do.eq(self.shared.do),
                    current_buf.intf.rdy.eq(self.shared.rdy),
                ]
                with m.If(self.shared.rdy):
                    with m.If(current_buf.intf.lock):
                        m.next = "REQUEST"
                    with m.Else():
                        m.next = "IDLE"

        return m


class GTPTXInit(Elaboratable):
    def __init__(self, ss_clock_frequency=125e6):
        self._ss_clock_frequency = ss_clock_frequency

        #
        # I/O port
        #
        self.done            = Signal()
        self.restart         = Signal()

        # GTP signals
        self.plllock         = Signal()
        self.pllreset        = Signal()
        self.gttxreset       = Signal()
        self.gttxpd          = Signal()
        self.txresetdone     = Signal()
        self.txdlysreset     = Signal()
        self.txdlysresetdone = Signal()
        self.txphinit        = Signal()
        self.txphinitdone    = Signal()
        self.txphalign       = Signal()
        self.txphaligndone   = Signal()
        self.txdlyen         = Signal()
        self.txuserrdy       = Signal()


    def elaborate(self, platform):
        m = Module()

        # Double-latch transceiver asynch outputs
        plllock         = Signal()
        txresetdone     = Signal()
        txdlysresetdone = Signal()
        txphinitdone    = Signal()
        txphaligndone   = Signal()
        m.submodules += [
            FFSynchronizer(self.plllock, plllock, o_domain="ss"),
            FFSynchronizer(self.txresetdone, txresetdone, o_domain="ss"),
            FFSynchronizer(self.txdlysresetdone, txdlysresetdone, o_domain="ss"),
            FFSynchronizer(self.txphinitdone, txphinitdone, o_domain="ss"),
            FFSynchronizer(self.txphaligndone, txphaligndone, o_domain="ss")
        ]

        # Deglitch FSM outputs driving transceiver asynch inputs
        gttxreset   = Signal()
        gttxpd      = Signal()
        txdlysreset = Signal()
        txphinit    = Signal()
        txphalign   = Signal()
        txdlyen     = Signal()
        txuserrdy   = Signal()
        m.d.ss += [
            self.gttxreset   .eq(gttxreset),
            self.gttxpd      .eq(gttxpd),
            self.txdlysreset .eq(txdlysreset),
            self.txphinit    .eq(txphinit),
            self.txphalign   .eq(txphalign),
            self.txdlyen     .eq(txdlyen),
            self.txuserrdy   .eq(txuserrdy)
        ]

        # Detect txphaligndone rising edge
        txphaligndone_r = Signal(reset=1)
        txphaligndone_rising = Signal()
        m.d.ss   += txphaligndone_r.eq(txphaligndone)
        m.d.comb += txphaligndone_rising.eq(txphaligndone & ~txphaligndone_r)

        # Wait 500ns after configuration before releasing
        # GTP reset (to follow AR43482)
        init_delay = WaitTimer(int(500e-9*self._ss_clock_frequency))
        m.submodules += init_delay
        m.d.comb += init_delay.wait.eq(1)


        with m.FSM(domain="ss"):
            with m.State("POWER-DOWN"):
                m.d.comb += [
                    self.pllreset.eq(1),
                    gttxreset.eq(1),
                    gttxpd.eq(1),
                ]
                m.next = "PLL-RESET"

            with m.State("PLL-RESET"):
                m.d.comb += [
                    self.pllreset.eq(1),
                    gttxreset.eq(1),
                ]
                m.next = "WAIT-PLL-RESET"

            with m.State("WAIT-PLL-RESET"):
                m.d.comb += gttxreset.eq(1)
                with m.If(plllock):
                    m.next = "WAIT-INIT-DELAY"

            with m.State("WAIT-INIT-DELAY"):
                m.d.comb += gttxreset.eq(1)
                with m.If(init_delay.done):
                    m.next = "WAIT-GTP-RESET"

            with m.State("WAIT-GTP-RESET"):
                m.d.comb += txuserrdy.eq(1)
                with m.If(txresetdone):
                    m.next = "READY"

            with m.State("READY"):
                m.d.comb += [
                    txuserrdy.eq(1),
                    txdlyen.eq(1),
                    self.done.eq(1),
                ]
                with m.If(self.restart):
                    m.next = "POWER-DOWN"


        # FSM watchdog / restart
        m.submodules.watchdog = watchdog = WaitTimer(int(1e-3*self._ss_clock_frequency))
        reset_self = self.restart | watchdog.done
        m.d.comb += watchdog.wait.eq(~reset_self & ~self.done),

        return ResetInserter(reset_self)(m)


class GTPRXInit(Elaboratable):
    def __init__(self, ss_clock_frequency):
        self._ss_clock_frequency = ss_clock_frequency

        #
        # I/O port
        #
        self.done            = Signal()
        self.restart         = Signal()

        # GTP signals
        self.plllock         = Signal()
        self.gtrxreset       = Signal()
        self.gtrxpd          = Signal()
        self.rxresetdone     = Signal()
        self.rxdlysreset     = Signal()
        self.rxdlysresetdone = Signal()
        self.rxphalign       = Signal()
        self.rxuserrdy       = Signal()
        self.rxsyncdone      = Signal()
        self.rxpmaresetdone  = Signal()

        self.drp             = DRPInterface()


    def elaborate(self, platform):
        m = Module()

        drpvalue = Signal(16)
        drpmask  = Signal()

        m.d.comb += [
            self.drp.lock.eq(1),
            self.drp.addr.eq(0x011)
        ]

        with m.If(drpmask):
            m.d.comb += self.drp.di.eq(drpvalue & 0xf7ff)
        with m.Else():
            m.d.comb += self.drp.di.eq(drpvalue)


        rxpmaresetdone = Signal()
        m.submodules += FFSynchronizer(self.rxpmaresetdone, rxpmaresetdone)
        rxpmaresetdone_r = Signal()
        m.d.ss += rxpmaresetdone_r.eq(rxpmaresetdone)

        # Double-latch transceiver asynch outputs
        plllock         = Signal()
        rxresetdone     = Signal()
        rxdlysresetdone = Signal()
        rxsyncdone      = Signal()
        m.submodules += [
            FFSynchronizer(self.plllock, plllock, o_domain="ss"),
            FFSynchronizer(self.rxresetdone, rxresetdone, o_domain="ss"),
            FFSynchronizer(self.rxdlysresetdone, rxdlysresetdone, o_domain="ss"),
            FFSynchronizer(self.rxsyncdone, rxsyncdone, o_domain="ss")
        ]

        # Deglitch FSM outputs driving transceiver asynch inputs
        gtrxreset   = Signal()
        gtrxpd      = Signal()
        rxdlysreset = Signal()
        rxphalign   = Signal()
        rxuserrdy   = Signal()
        m.d.ss += [
            self.gtrxreset    .eq(gtrxreset),
            self.gtrxpd       .eq(gtrxpd),
            self.rxdlysreset  .eq(rxdlysreset),
            self.rxphalign    .eq(rxphalign),
            self.rxuserrdy    .eq(rxuserrdy)
        ]

        # Wait 500ns after configuration before releasing
        # GTP reset (to follow AR43482)
        init_delay = WaitTimer(int(500e-9*self._ss_clock_frequency))
        m.submodules += init_delay
        m.d.comb += init_delay.wait.eq(1)

        with m.FSM(domain="ss"):
            with m.State("POWER-DOWN"):
                m.d.comb += [
                    gtrxreset.eq(1),
                    gtrxpd.eq(1),
                ]
                m.next = "DRP_READ_ISSUE"

            with m.State("DRP_READ_ISSUE"):
                m.d.comb += gtrxreset.eq(1)
                with m.If(init_delay.done):
                    m.next = "DRP_READ_ISSUE_POST"

            with m.State("DRP_READ_ISSUE_POST"):
                m.d.comb += [
                    gtrxreset.eq(1),
                    self.drp.en.eq(1),
                ]
                m.next = "DRP_READ_WAIT"

            with m.State("DRP_READ_WAIT"):
                m.d.comb += gtrxreset.eq(1)
                with m.If(self.drp.rdy):
                    m.d.ss += drpvalue.eq(self.drp.do)
                    m.next = "DRP_MOD_ISSUE"

            with m.State("DRP_MOD_ISSUE"):
                m.d.comb += [
                    gtrxreset.eq(1),
                    drpmask.eq(1),
                    self.drp.en.eq(1),
                    self.drp.we.eq(1),
                ]
                m.next = "DRP_MOD_WAIT"


            with m.State("DRP_MOD_WAIT"):
                m.d.comb += gtrxreset.eq(1)
                with m.If(self.drp.rdy):
                    m.next = "WAIT_PMARST_FALL"

            with m.State("WAIT_PMARST_FALL"):
                m.d.comb += rxuserrdy.eq(1)
                with m.If(rxpmaresetdone_r & ~rxpmaresetdone):
                    m.next = "DRP_RESTORE_ISSUE"


            with m.State("DRP_RESTORE_ISSUE"):
                m.d.comb += [
                    rxuserrdy.eq(1),
                    self.drp.en.eq(1),
                    self.drp.we.eq(1),
                ]
                m.next = "DRP_RESTORE_WAIT"

            with m.State("DRP_RESTORE_WAIT"):
                m.d.comb += rxuserrdy.eq(1)
                with m.If(self.drp.rdy):
                    m.next = "WAIT-GTP-RESET"

            with m.State("WAIT-GTP-RESET"):
                m.d.comb += rxuserrdy.eq(1)
                with m.If(rxresetdone):
                    m.next = "READY"

            with m.State("READY"):
                m.d.comb += [
                    rxuserrdy.eq(1),
                    self.done.eq(1),
                    self.drp.lock.eq(0),
                ]
                with m.If(self.restart):
                    m.next = "POWER-DOWN"

        # FSM watchdog / restart
        m.submodules.watchdog = watchdog = WaitTimer(int(4e-3*self._ss_clock_frequency))
        reset_self = watchdog.done | self.restart
        m.d.comb += watchdog.wait.eq(~reset_self & ~self.done),

        return ResetInserter(reset_self)(m)


class GTPRXTermination(Elaboratable):
    def __init__(self):
        self.drp = DRPInterface()

        self.enable = Signal()


    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.drp.lock.eq(1),
            self.drp.addr.eq(0x0011)
        ]

        reg_rx_cfg = Signal(15)

        rx_cm_sel_cur = reg_rx_cfg[4:6]
        rx_cm_sel_new = Mux(self.enable,
                            0b11, # Programmable
                            0b10) # Floating

        with m.FSM(domain="ss"):
            with m.State("READ"):
                m.d.comb += [
                    self.drp.en.eq(1)
                ]
                m.next = "READ-WAIT"

            with m.State("READ-WAIT"):
                with m.If(self.drp.rdy):
                    m.d.ss += [
                        reg_rx_cfg.eq(self.drp.do),
                        rx_cm_sel_cur.eq(rx_cm_sel_new)
                    ]
                    m.next = "WRITE"

            with m.State("WRITE"):
                m.d.comb += [
                    self.drp.di.eq(reg_rx_cfg),
                    self.drp.we.eq(1),
                    self.drp.en.eq(1),
                ]
                m.next = "WRITE-WAIT"

            with m.State("WRITE-WAIT"):
                with m.If(self.drp.rdy):
                    m.next = "IDLE"

            with m.State("IDLE"):
                m.d.comb += self.drp.lock.eq(0)
                with m.If(rx_cm_sel_cur != rx_cm_sel_new):
                    m.next = "READ"

        return m



class Open(Signal):
    pass


class GTPQuadPLL(Elaboratable):
    def __init__(self, refclk, refclk_freq, linerate, channel=0, shared=False):
        assert channel in [0, 1]
        self.channel     = channel

        self._refclk      = refclk
        self._refclk_freq = refclk_freq
        self._linerate    = linerate
        self._shared      = shared

        #
        # I/O port
        #
        self.clk     = Signal()
        self.refclk  = Signal()
        self.reset   = Signal()
        self.lock    = Signal()
        self.config  = self.compute_config(refclk_freq, linerate)

        # DRP
        self.drp = DRPInterface()


    def elaborate(self, platform):
        m = Module()
        config = self.config

        if not self._shared:
            gtpe2_common_params = dict(
                # common
                i_GTREFCLK0    = self._refclk,
                i_BGBYPASSB    = 1,
                i_BGMONITORENB = 1,
                i_BGPDB        = 1,
                i_BGRCALOVRD   = 0b11111,
                i_RCALENB      = 1,

                i_DRPCLK       = ClockSignal("ss"),
                i_DRPADDR      = self.drp.addr,
                i_DRPDI        = self.drp.di,
                o_DRPDO        = self.drp.do,
                i_DRPWE        = self.drp.we,
                i_DRPEN        = self.drp.en,
                o_DRPRDY       = self.drp.rdy,
            )

            if self.channel == 0:
                gtpe2_common_params.update(
                    # pll0
                    p_PLL0_FBDIV      = config["n2"],
                    p_PLL0_FBDIV_45   = config["n1"],
                    p_PLL0_REFCLK_DIV = config["m"],
                    i_PLL0LOCKEN      = 1,
                    i_PLL0PD          = 0,
                    i_PLL0REFCLKSEL   = 0b001,
                    i_PLL0RESET       = self.reset,
                    o_PLL0LOCK        = self.lock,
                    o_PLL0OUTCLK      = self.clk,
                    o_PLL0OUTREFCLK   = self.refclk,

                    # pll1 (not used: power down)
                    i_PLL1PD          = 1,
                )
            else:
                gtpe2_common_params.update(
                    # pll0 (not used: power down)
                    i_PLL0PD          = 1,

                    # pll0
                    p_PLL1_FBDIV      = config["n2"],
                    p_PLL1_FBDIV_45   = config["n1"],
                    p_PLL1_REFCLK_DIV = config["m"],
                    i_PLL1LOCKEN      = 1,
                    i_PLL1PD          = 0,
                    i_PLL1REFCLKSEL   = 0b001,
                    i_PLL1RESET       = self.reset,
                    o_PLL1LOCK        = self.lock,
                    o_PLL1OUTCLK      = self.clk,
                    o_PLL1OUTREFCLK   = self.refclk,
                )

            m.submodules += Instance("GTPE2_COMMON", **gtpe2_common_params)
        else:
            self.gtrefclk  = self._refclk
            self.gtgrefclk = 0
            self.refclksel = 0b010

        return m


    @staticmethod
    def compute_config(refclk_freq, linerate):
        for n1 in 4, 5:
            for n2 in 1, 2, 3, 4, 5:
                for m in 1, 2:
                    vco_freq = refclk_freq*(n1*n2)/m
                    if 1.6e9 <= vco_freq <= 3.3e9:
                        for d in 1, 2, 4, 8, 16:
                            current_linerate = vco_freq*2/d
                            if current_linerate == linerate:
                                return {"n1": n1, "n2": n2, "m": m, "d": d,
                                        "vco_freq": vco_freq,
                                        "clkin": refclk_freq,
                                        "linerate": linerate}
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))

    def __repr__(self):
        config = self.config
        r = """
GTPQuadPLL
==============
  overview:
  ---------
       +--------------------------------------------------+
       |                                                  |
       |   +-----+  +---------------------------+ +-----+ |
       |   |     |  | Phase Frequency Detector  | |     | |
CLKIN +----> /M  +-->       Charge Pump         +-> VCO +---> CLKOUT
       |   |     |  |       Loop Filter         | |     | |
       |   +-----+  +---------------------------+ +--+--+ |
       |              ^                              |    |
       |              |    +-------+    +-------+    |    |
       |              +----+  /N2  <----+  /N1  <----+    |
       |                   +-------+    +-------+         |
       +--------------------------------------------------+
                            +-------+
                   CLKOUT +->  2/D  +-> LINERATE
                            +-------+
  config:
  -------
    CLKIN    = {clkin}MHz
    CLKOUT   = CLKIN x (N1 x N2) / M = {clkin}MHz x ({n1} x {n2}) / {m}
             = {vco_freq}GHz
    LINERATE = CLKOUT x 2 / D = {vco_freq}GHz x 2 / {d}
             = {linerate}GHz
""".format(clkin    = config["clkin"]/1e6,
           n1       = config["n1"],
           n2       = config["n2"],
           m        = config["m"],
           vco_freq = config["vco_freq"]/1e9,
           d        = config["d"],
           linerate = config["linerate"]/1e9)
        return r


class GTP(Elaboratable):
    def __init__(self, qpll, tx_pads, rx_pads, ss_clock_frequency):
        self._qpll    = qpll
        self._tx_pads = tx_pads
        self._rx_pads = rx_pads
        self._ss_clock_frequency = ss_clock_frequency

        self.data_width = 20
        self.nwords = self.data_width // 10

        # Streams
        self.sink   = USBRawSuperSpeedStream(payload_words=2)
        self.source = USBRawSuperSpeedStream(payload_words=2)

        self.reset           = Signal()

        # TX controls
        self.tx_enable       = Signal(reset=1)
        self.tx_polarity     = Signal()
        self.tx_ready        = Signal()
        self.tx_idle         = Signal()
        self.tx_inhibit      = Signal()
        self.tx_gpio_en      = Signal()
        self.tx_gpio         = Signal()

        # RX controls
        self.rx_enable       = Signal(reset=1)
        self.rx_polarity     = Signal()
        self.rx_termination  = Signal()
        self.rx_ready        = Signal()
        self.rx_align        = Signal(reset=1)
        self.rx_idle         = Signal()
        self.train_equalizer = Signal()


        # DRP
        self.drp = DRPInterface()

        # Loopback
        self.loopback = Signal(3)

        # Transceiver direct clock outputs (useful to specify clock constraints)
        self.txoutclk = Signal()
        self.rxoutclk = Signal()


    def elaborate(self, platform):
        m = Module()

        # Aliases.
        qpll       = self._qpll
        data_width = self.data_width
        nwords     = self.nwords

        # Ensure we have a valid PLL/CDR configuration.
        assert qpll.config["linerate"] < 6.6e9
        # From [UG482: Table 4-14]: CDR Recommended Settings for Protocols with SSC
        rxcdr_cfgs = {
            1 : 0x0000087FE206024481010,
            2 : 0x0000047FE206024501010,
            4 : 0x0000047FE106024501010,
        }


        #
        # Transciever GPIO synchronization
        #
        tx_polarity     = Signal()
        tx_gpio_en      = Signal()
        tx_gpio         = Signal()
        m.submodules += [
            FFSynchronizer(self.tx_polarity, tx_polarity, o_domain="tx"),
            FFSynchronizer(self.tx_gpio_en,  tx_gpio_en,  o_domain="tx"),
            FFSynchronizer(self.tx_gpio,     tx_gpio,     o_domain="tx"),
        ]

        rx_polarity     = Signal()
        m.submodules += [
            FFSynchronizer(self.rx_polarity, rx_polarity, o_domain="rx"),
        ]



        #
        # Transmitter bringup.
        #
        m.submodules.tx_init = tx_init = ResetInserter({"ss": self.reset})(GTPTXInit(self._ss_clock_frequency))
        m.d.comb += [
            self.tx_ready    .eq(tx_init.done),
            tx_init.restart  .eq(~self.tx_enable)
        ]

        #
        # Receiver bringup.
        #
        m.submodules.rx_init = rx_init = ResetInserter({"ss": self.reset})(GTPRXInit(self._ss_clock_frequency))
        m.d.comb += [
            self.rx_ready.eq(rx_init.done),
            rx_init.restart.eq(~self.rx_enable)
        ]

        #
        # PLL interconnection
        #
        m.d.comb += [
            tx_init.plllock.eq(qpll.lock),
            rx_init.plllock.eq(qpll.lock),
            qpll.reset.eq(tx_init.pllreset)
        ]

        #
        # RX termination
        #
        m.submodules.rx_term = rx_term = GTPRXTermination()
        m.d.comb += [
            rx_term.enable.eq(self.rx_termination),
        ]

        #
        # DRP
        #
        m.submodules.drp_arbiter = drp_arbiter = self.drp_arbiter = DRPArbiter()
        drp_arbiter.add_interface(rx_init.drp)
        drp_arbiter.add_interface(rx_term.drp)
        drp_arbiter.add_interface(self.drp)

        #
        # LFPS "logic clock"
        #

        # The OOB unit requires a psuedo-clock that operates at 50% duty cycle,
        # and which is slower than the clocks used by the rest of units.
        lfps_counter   = Signal(3)
        lfps_logic_clk = lfps_counter[-1]
        m.d.ss += lfps_counter.eq(lfps_counter + 1)


        #
        # Core SerDes-chnannel IP instance
        #
        rxphaligndone = Signal()

        # Transmitter data signals.
        tx_data       = Signal(8 * nwords)
        tx_ctrl       = Signal(nwords)

        # Receiver data signals.
        rx_data       = Signal(8 * nwords)
        rx_ctrl       = Signal(nwords)
        rx_disp_error = Signal(nwords)
        rx_code_error = Signal(nwords)


        m.submodules.gtp = Instance("GTPE2_CHANNEL",
            # Simulation-Only Attributes
            p_SIM_RECEIVER_DETECT_PASS   = "TRUE",
            p_SIM_TX_EIDLE_DRIVE_LEVEL   = "X",
            p_SIM_RESET_SPEEDUP          = "FALSE",
            p_SIM_VERSION                = "2.0",

            # RX Byte and Word Alignment Attributes
            p_ALIGN_COMMA_DOUBLE         = "FALSE",
            p_ALIGN_COMMA_ENABLE         = 0b11_1111_1111,
            #p_ALIGN_COMMA_WORD           = 2,
            p_ALIGN_COMMA_WORD           = 1,
            p_ALIGN_MCOMMA_DET           = "TRUE",
            p_ALIGN_MCOMMA_VALUE         = 0b10_1000_0011,
            p_ALIGN_PCOMMA_DET           = "TRUE",
            p_ALIGN_PCOMMA_VALUE         = 0b01_0111_1100,
            p_SHOW_REALIGN_COMMA         = "TRUE",
            p_RXSLIDE_AUTO_WAIT          = 7,
            p_RXSLIDE_MODE               = "OFF",
            p_RX_SIG_VALID_DLY           = 10,

            # RX 8B/10B Decoder Attributes
            p_RX_DISPERR_SEQ_MATCH       = "FALSE",
            p_DEC_MCOMMA_DETECT          = "TRUE",
            p_DEC_PCOMMA_DETECT          = "TRUE",
            p_DEC_VALID_COMMA_ONLY       = "TRUE",

            # RX Clock Correction Attributes
            p_CBCC_DATA_SOURCE_SEL       = "DECODED",
            p_CLK_COR_SEQ_2_USE          = "FALSE",
            p_CLK_COR_KEEP_IDLE          = "FALSE",
            p_CLK_COR_MAX_LAT            = 10,
            p_CLK_COR_MIN_LAT            = 8,
            p_CLK_COR_PRECEDENCE         = "TRUE",
            p_CLK_COR_REPEAT_WAIT        = 0,
            p_CLK_COR_SEQ_LEN            = 2,
            p_CLK_COR_SEQ_1_ENABLE       = 0b1100,
            p_CLK_COR_SEQ_1_1            = 0b0000000000,
            p_CLK_COR_SEQ_1_2            = 0b0000000000,
            p_CLK_COR_SEQ_1_3            = 0b0000000000,
            p_CLK_COR_SEQ_1_4            = 0b0000000000,
            p_CLK_CORRECT_USE            = "FALSE",
            p_CLK_COR_SEQ_2_ENABLE       = 0b1111,
            p_CLK_COR_SEQ_2_1            = 0b0000000000,
            p_CLK_COR_SEQ_2_2            = 0b0000000000,
            p_CLK_COR_SEQ_2_3            = 0b0000000000,
            p_CLK_COR_SEQ_2_4            = 0b0000000000,

            # RX Channel Bonding Attributes
            p_CHAN_BOND_KEEP_ALIGN       = "FALSE",
            p_CHAN_BOND_MAX_SKEW         = 1,
            p_CHAN_BOND_SEQ_LEN          = 1,
            p_CHAN_BOND_SEQ_1_1          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_2          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_3          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_4          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_ENABLE     = 0b1111,
            p_CHAN_BOND_SEQ_2_1          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_2          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_3          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_4          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_ENABLE     = 0b1111,
            p_CHAN_BOND_SEQ_2_USE        = "FALSE",
            p_FTS_DESKEW_SEQ_ENABLE      = 0b1111,
            p_FTS_LANE_DESKEW_CFG        = 0b1111,
            p_FTS_LANE_DESKEW_EN         = "FALSE",

            # RX Margin Analysis Attributes
            p_ES_CONTROL                 = 0b000000,
            p_ES_ERRDET_EN               = "FALSE",
            p_ES_EYE_SCAN_EN             = "TRUE",
            p_ES_HORZ_OFFSET             = 0x000,
            p_ES_PMA_CFG                 = 0b0000000000,
            p_ES_PRESCALE                = 0b00000,
            p_ES_QUALIFIER               = 0x00000000000000000000,
            p_ES_QUAL_MASK               = 0x00000000000000000000,
            p_ES_SDATA_MASK              = 0x00000000000000000000,
            p_ES_VERT_OFFSET             = 0b000000000,

            # FPGA RX Interface Attributes
            p_RX_DATA_WIDTH              = data_width,

            # PMA Attributes
            p_OUTREFCLK_SEL_INV          = 0b11,
            p_PMA_RSV                    = 0x00000333,
            p_PMA_RSV2                   = 0x00002040,
            p_PMA_RSV3                   = 0b00,
            p_PMA_RSV4                   = 0b0000,
            p_RX_BIAS_CFG                = 0b0000111100110011,
            p_DMONITOR_CFG               = 0x000A00,
            p_RX_DEBUG_CFG               = 0b00000000000000,
            p_RX_OS_CFG                  = 0b0000010000000,
            p_TERM_RCAL_CFG              = 0b100001000010000,
            p_TERM_RCAL_OVRD             = 0b000,
            p_TST_RSV                    = 0x00000000,
            p_RX_CLK25_DIV               = 5,
            p_TX_CLK25_DIV               = 5,
            p_UCODEER_CLR                = 0b0,

            # PCI Express Attributes
            p_PCS_PCIE_EN                = "FALSE",

            # PCS Attributes
            p_PCS_RSVD_ATTR              = 0x000000000100,

            # RX Buffer Attributes
            p_RXBUF_ADDR_MODE            = "FAST",
            p_RXBUF_EIDLE_HI_CNT         = 0b1000,
            p_RXBUF_EIDLE_LO_CNT         = 0b0000,
            p_RXBUF_EN                   = "TRUE",
            p_RX_BUFFER_CFG              = 0b000000,
            p_RXBUF_RESET_ON_CB_CHANGE   = "TRUE",
            p_RXBUF_RESET_ON_COMMAALIGN  = "FALSE",
            p_RXBUF_RESET_ON_EIDLE       = "FALSE",
            p_RXBUF_RESET_ON_RATE_CHANGE = "TRUE",
            p_RXBUFRESET_TIME            = 0b00001,
            p_RXBUF_THRESH_OVFLW         = 61,
            p_RXBUF_THRESH_OVRD          = "FALSE",
            p_RXBUF_THRESH_UNDFLW        = 4,
            p_RXDLY_CFG                  = 0x001F,
            p_RXDLY_LCFG                 = 0x030,
            p_RXDLY_TAP_CFG              = 0x0000,
            p_RXPH_CFG                   = 0xC00002,
            p_RXPHDLY_CFG                = 0x084020,
            p_RXPH_MONITOR_SEL           = 0b00000,
            p_RX_XCLK_SEL                = "RXREC",
            p_RX_DDI_SEL                 = 0b000000,
            p_RX_DEFER_RESET_BUF_EN      = "TRUE",

            # CDR Attributes
            p_RXCDR_CFG                  = rxcdr_cfgs[qpll.config["d"]],
            p_RXCDR_FR_RESET_ON_EIDLE    = 0b0,
            p_RXCDR_HOLD_DURING_EIDLE    = 0b0,
            p_RXCDR_PH_RESET_ON_EIDLE    = 0b0,
            p_RXCDR_LOCK_CFG             = 0b001001,

            # RX Initialization and Reset Attributes
            p_RXCDRFREQRESET_TIME        = 0b00001,
            p_RXCDRPHRESET_TIME          = 0b00001,
            p_RXISCANRESET_TIME          = 0b00001,
            p_RXPCSRESET_TIME            = 0b00001,
            p_RXPMARESET_TIME            = 0b00011,

            # RX OOB Signaling Attributes
            p_RXOOB_CFG                  = 0b0000110,

            # RX Gearbox Attributes
            p_RXGEARBOX_EN               = "FALSE",
            p_GEARBOX_MODE               = 0b000,

            # PRBS Detection Attribute
            p_RXPRBS_ERR_LOOPBACK        = 0b0,

            # Power-Down Attributes
            p_PD_TRANS_TIME_FROM_P2      = 0x03c,
            p_PD_TRANS_TIME_NONE_P2      = 0x3c,
            p_PD_TRANS_TIME_TO_P2        = 0x64,

            # RX OOB Signaling Attributes
            p_SAS_MAX_COM                = 64,
            p_SAS_MIN_COM                = 36,
            p_SATA_BURST_SEQ_LEN         = 0b0101,
            p_SATA_BURST_VAL             = 0b100,
            p_SATA_EIDLE_VAL             = 0b100,
            p_SATA_MAX_BURST             = 8,
            p_SATA_MAX_INIT              = 21,
            p_SATA_MAX_WAKE              = 7,
            p_SATA_MIN_BURST             = 4,
            p_SATA_MIN_INIT              = 12,
            p_SATA_MIN_WAKE              = 4,

            # RX Fabric Clock Output Control Attributes
            p_TRANS_TIME_RATE            = 0x0E,

            # TX Buffer Attributes
            p_TXBUF_EN                   = "TRUE",
            p_TXBUF_RESET_ON_RATE_CHANGE = "TRUE",
            p_TXDLY_CFG                  = 0x001F,
            p_TXDLY_LCFG                 = 0x030,
            p_TXDLY_TAP_CFG              = 0x0000,
            p_TXPH_CFG                   = 0x0780,
            p_TXPHDLY_CFG                = 0x084020,
            p_TXPH_MONITOR_SEL           = 0b00000,
            p_TX_XCLK_SEL                = "TXOUT",

            # FPGA TX Interface Attributes
            p_TX_DATA_WIDTH              = data_width,

            # TX Configurable Driver Attributes
            p_TX_DEEMPH0                 = 0b000000,
            p_TX_DEEMPH1                 = 0b000000,
            p_TX_EIDLE_ASSERT_DELAY      = 0b110,
            p_TX_EIDLE_DEASSERT_DELAY    = 0b100,
            p_TX_LOOPBACK_DRIVE_HIZ      = "FALSE",
            p_TX_MAINCURSOR_SEL          = 0b0,
            p_TX_DRIVE_MODE              = "DIRECT",
            p_TX_MARGIN_FULL_0           = 0b1001110,
            p_TX_MARGIN_FULL_1           = 0b1001001,
            p_TX_MARGIN_FULL_2           = 0b1000101,
            p_TX_MARGIN_FULL_3           = 0b1000010,
            p_TX_MARGIN_FULL_4           = 0b1000000,
            p_TX_MARGIN_LOW_0            = 0b1000110,
            p_TX_MARGIN_LOW_1            = 0b1000100,
            p_TX_MARGIN_LOW_2            = 0b1000010,
            p_TX_MARGIN_LOW_3            = 0b1000000,
            p_TX_MARGIN_LOW_4            = 0b1000000,

            # TX Gearbox Attributes
            p_TXGEARBOX_EN               = "FALSE",

            # TX Initialization and Reset Attributes
            p_TXPCSRESET_TIME            = 0b00001,
            p_TXPMARESET_TIME            = 0b00001,

            # TX Receiver Detection Attributes
            p_TX_RXDETECT_CFG            = 0x1832,
            p_TX_RXDETECT_REF            = 0b100,

            # JTAG Attributes
            p_ACJTAG_DEBUG_MODE          = 0b0,
            p_ACJTAG_MODE                = 0b0,
            p_ACJTAG_RESET               = 0b0,

            # CDR Attributes
            p_CFOK_CFG                   = 0x49000040E80,
            p_CFOK_CFG2                  = 0b0100000,
            p_CFOK_CFG3                  = 0b0100000,
            p_CFOK_CFG4                  = 0b0,
            p_CFOK_CFG5                  = 0x0,
            p_CFOK_CFG6                  = 0b0000,
            p_RXOSCALRESET_TIME          = 0b00011,
            p_RXOSCALRESET_TIMEOUT       = 0b00000,

            # PMA Attributes
            p_CLK_COMMON_SWING           = 0b0,
            p_RX_CLKMUX_EN               = 0b1,
            p_TX_CLKMUX_EN               = 0b1,
            p_ES_CLK_PHASE_SEL           = 0b0,
            p_USE_PCS_CLK_PHASE_SEL      = 0b0,
            p_PMA_RSV6                   = 0b0,
            p_PMA_RSV7                   = 0b0,

            # TX Configuration Driver Attributes
            p_TX_PREDRIVER_MODE          = 0b0,
            p_PMA_RSV5                   = 0b0,
            p_SATA_PLL_CFG               = "VCO_3000MHZ",

            # RX Fabric Clock Output Control Attributes
            p_RXOUT_DIV                  = qpll.config["d"],

            # TX Fabric Clock Output Control Attributes
            p_TXOUT_DIV                  = qpll.config["d"],

            # RX Phase Interpolator Attributes
            p_RXPI_CFG0                  = 0b000,
            p_RXPI_CFG1                  = 0b1,
            p_RXPI_CFG2                  = 0b1,

            # RX Equalizer Attributes
            p_ADAPT_CFG0                 = 0x00000,
            p_RXLPMRESET_TIME            = 0b0001111,
            p_RXLPM_BIAS_STARTUP_DISABLE = 0b0,
            p_RXLPM_CFG                  = 0b0110,
            p_RXLPM_CFG1                 = 0b0,
            p_RXLPM_CM_CFG               = 0b0,
            p_RXLPM_GC_CFG               = 0b111100010,
            p_RXLPM_GC_CFG2              = 0b001,
            p_RXLPM_HF_CFG               = 0b00001111110000,
            p_RXLPM_HF_CFG2              = 0b01010,
            p_RXLPM_HF_CFG3              = 0b0000,
            p_RXLPM_HOLD_DURING_EIDLE    = 0b0,
            p_RXLPM_INCM_CFG             = 0b1,
            p_RXLPM_IPCM_CFG             = 0b0,
            p_RXLPM_LF_CFG               = 0b000000001111110000,
            p_RXLPM_LF_CFG2              = 0b01010,
            p_RXLPM_OSINT_CFG            = 0b100,

            # TX Phase Interpolator PPM Controller Attributes
            p_TXPI_CFG0                  = 0b00,
            p_TXPI_CFG1                  = 0b00,
            p_TXPI_CFG2                  = 0b00,
            p_TXPI_CFG3                  = 0b0,
            p_TXPI_CFG4                  = 0b0,
            p_TXPI_CFG5                  = 0b000,
            p_TXPI_GREY_SEL              = 0b0,
            p_TXPI_INVSTROBE_SEL         = 0b0,
            p_TXPI_PPMCLK_SEL            = "TXUSRCLK2",
            p_TXPI_PPM_CFG               = 0x00,
            p_TXPI_SYNFREQ_PPM           = 0b001,

            # LOOPBACK Attributes
            p_LOOPBACK_CFG               = 0b0,
            p_PMA_LOOPBACK_CFG           = 0b0,

            p_RX_CM_SEL                  = 0b10,
            p_RX_CM_TRIM                 = 0b1010,

            # RX OOB Signalling Attributes
            p_RXOOB_CLK_CFG              = "FABRIC",

            # TX OOB Signalling Attributes
            p_TXOOB_CFG                  = 0b0,

            # RX Buffer Attributes
            p_RXSYNC_MULTILANE           = 0b0,
            p_RXSYNC_OVRD                = 0b0,
            p_RXSYNC_SKIP_DA             = 0b0,

            # TX Buffer Attributes
            p_TXSYNC_MULTILANE           = 0b0,
            p_TXSYNC_OVRD                = 0b1,
            p_TXSYNC_SKIP_DA             = 0b0,

            # CPLL Ports
            i_GTRSVD                = 0b0000000000000000,
            i_PCSRSVDIN             = 0b0000000000000000,
            i_TSTIN                 = 0b11111111111111111111,

            # Channel - DRP Ports
            i_DRPCLK                = ClockSignal("ss"),
            i_DRPADDR               = drp_arbiter.shared.addr,
            i_DRPDI                 = drp_arbiter.shared.di,
            o_DRPDO                 = drp_arbiter.shared.do,
            i_DRPWE                 = drp_arbiter.shared.we,
            i_DRPEN                 = drp_arbiter.shared.en,
            o_DRPRDY                = drp_arbiter.shared.rdy,

            # Clocking Ports
            i_RXSYSCLKSEL           = 0b00 if qpll.channel == 0 else 0b11,
            i_TXSYSCLKSEL           = 0b00 if qpll.channel == 0 else 0b11,

            # FPGA TX Interface Datapath Configuration
            i_TX8B10BEN             = 1,

            # GTPE2_CHANNEL Clocking Ports
            i_PLL0CLK               = qpll.clk    if qpll.channel == 0 else 0,
            i_PLL0REFCLK            = qpll.refclk if qpll.channel == 0 else 0,
            i_PLL1CLK               = qpll.clk    if qpll.channel == 1 else 0,
            i_PLL1REFCLK            = qpll.refclk if qpll.channel == 1 else 0,

            # Loopback Ports
            i_LOOPBACK              = self.loopback,

            # PCI Express Ports
            o_PHYSTATUS             = Open(),
            i_RXRATE                = 0,
            o_RXVALID               = Open(),

            # PMA Reserved Ports
            i_PMARSVDIN3            = 0b0,
            i_PMARSVDIN4            = 0b0,

            # Power-Down Ports
            i_RXPD                  = Cat(rx_init.gtrxpd, rx_init.gtrxpd),
            i_TXPD                  = 0b00,

            # RX 8B/10B Decoder Ports
            i_SETERRSTATUS          = 0,

            # RX Initialization and Reset Ports
            i_EYESCANRESET          = 0,
            i_RXUSERRDY             = rx_init.rxuserrdy,

            # RX Margin Analysis Ports
            o_EYESCANDATAERROR      = Open(),
            i_EYESCANMODE           = 0,
            i_EYESCANTRIGGER        = 0,

            # Receive Ports
            i_CLKRSVD0              = 0,
            i_CLKRSVD1              = 0,
            i_DMONFIFORESET         = 0,
            i_DMONITORCLK           = 0,
            o_RXPMARESETDONE        = rx_init.rxpmaresetdone,
            i_SIGVALIDCLK           = lfps_logic_clk,

            # Receive Ports - CDR Ports
            i_RXCDRFREQRESET        = 0,
            i_RXCDRHOLD             = 0,
            o_RXCDRLOCK             = Open(),
            i_RXCDROVRDEN           = 0,
            i_RXCDRRESET            = 0,
            i_RXCDRRESETRSV         = 0,
            i_RXOSCALRESET          = 0,
            i_RXOSINTCFG            = 0b0010,
            o_RXOSINTDONE           = Open(),
            i_RXOSINTHOLD           = 0,
            i_RXOSINTOVRDEN         = 0,
            i_RXOSINTPD             = 0,
            o_RXOSINTSTARTED        = Open(),
            i_RXOSINTSTROBE         = 0,
            o_RXOSINTSTROBESTARTED  = Open(),
            i_RXOSINTTESTOVRDEN     = 0,

            # Receive Ports - Clock Correction Ports
            o_RXCLKCORCNT           = Open(2),

            # Receive Ports - FPGA RX Interface Datapath Configuration
            i_RX8B10BEN             = 1,

            # Receive Ports - FPGA RX Interface Ports
            o_RXDATA                = rx_data,
            i_RXUSRCLK              = ClockSignal("rx"),
            i_RXUSRCLK2             = ClockSignal("rx"),

            # Receive Ports - Pattern Checker Ports
            o_RXPRBSERR             = Open(),
            i_RXPRBSSEL             = 0,

            # Receive Ports - Pattern Checker ports
            i_RXPRBSCNTRESET        = 0,

            # Receive Ports - RX 8B/10B Decoder Ports
            o_RXCHARISCOMMA         = Open(2),
            o_RXCHARISK             = rx_ctrl,
            o_RXDISPERR             = rx_disp_error,
            o_RXNOTINTABLE          = rx_code_error,

            # Receive Ports - RX AFE Ports
            i_GTPRXN                = self._rx_pads.n,
            i_GTPRXP                = self._rx_pads.p,
            i_PMARSVDIN2            = 0b0,
            o_PMARSVDOUT0           = Open(),
            o_PMARSVDOUT1           = Open(),

            # Receive Ports - RX Buffer Bypass Ports
            i_RXBUFRESET            = 0,
            o_RXBUFSTATUS           = Open(3),
            i_RXDDIEN               = 0,
            i_RXDLYBYPASS           = 1,
            i_RXDLYEN               = 0,
            i_RXDLYOVRDEN           = 0,
            i_RXDLYSRESET           = rx_init.rxdlysreset,
            o_RXDLYSRESETDONE       = rx_init.rxdlysresetdone,
            i_RXPHALIGN             = 0,
            o_RXPHALIGNDONE         = rxphaligndone,
            i_RXPHALIGNEN           = 0,
            i_RXPHDLYPD             = 0,
            i_RXPHDLYRESET          = 0,
            o_RXPHMONITOR           = Open(5),
            i_RXPHOVRDEN            = 0,
            o_RXPHSLIPMONITOR       = Open(5),
            o_RXSTATUS              = Open(3),
            i_RXSYNCALLIN           = rxphaligndone,
            o_RXSYNCDONE            = rx_init.rxsyncdone,
            i_RXSYNCIN              = 0,
            i_RXSYNCMODE            = 0,
            o_RXSYNCOUT             = Open(),

            # Receive Ports - RX Byte and Word Alignment Ports
            o_RXBYTEISALIGNED       = Open(),
            o_RXBYTEREALIGN         = Open(),
            o_RXCOMMADET            = Open(),
            i_RXCOMMADETEN          = 1,
            i_RXMCOMMAALIGNEN       = self.rx_align,
            i_RXPCOMMAALIGNEN       = self.rx_align,
            i_RXSLIDE               = 0,

            # Receive Ports - RX Channel Bonding Ports
            o_RXCHANBONDSEQ         = Open(),
            i_RXCHBONDEN            = 0,
            i_RXCHBONDI             = 0b0000,
            i_RXCHBONDLEVEL         = 0,
            i_RXCHBONDMASTER        = 0,
            o_RXCHBONDO             = Open(4),
            i_RXCHBONDSLAVE         = 0,

            # Receive Ports - RX Channel Bonding Ports
            o_RXCHANISALIGNED       = Open(),
            o_RXCHANREALIGN         = Open(),

            # Receive Ports - RX Decision Feedback Equalizer
            o_DMONITOROUT           = Open(15),
            i_RXADAPTSELTEST        = 0,
            i_RXDFEXYDEN            = 0,
            i_RXOSINTEN             = 0b1,
            i_RXOSINTID0            = 0,
            i_RXOSINTNTRLEN         = 0,
            o_RXOSINTSTROBEDONE     = Open(),

            # Receive Ports - RX Driver,OOB signalling,Coupling and Eq.,CDR
            i_RXLPMLFOVRDEN         = 0,
            i_RXLPMOSINTNTRLEN      = 0,

            # Receive Ports - RX Equalizer Ports
            i_RXLPMHFHOLD           = ~self.train_equalizer,
            i_RXLPMHFOVRDEN         = 0,
            i_RXLPMLFHOLD           = ~self.train_equalizer,
            i_RXOSHOLD              = 0,
            i_RXOSOVRDEN            = 0,

            # Receive Ports - RX Fabric ClocK Output Control Ports
            o_RXRATEDONE            = Open(),

            # Receive Ports - RX Fabric Clock Output Control Ports
            i_RXRATEMODE            = 0b0,

            # Receive Ports - RX Fabric Output Control Ports
            o_RXOUTCLK              = self.rxoutclk,
            o_RXOUTCLKFABRIC        = Open(),
            o_RXOUTCLKPCS           = Open(),
            i_RXOUTCLKSEL           = 0b010,

            # Receive Ports - RX Gearbox Ports
            o_RXDATAVALID           = Open(2),
            o_RXHEADER              = Open(3),
            o_RXHEADERVALID         = Open(),
            o_RXSTARTOFSEQ          = Open(2),
            i_RXGEARBOXSLIP         = 0,

            # Receive Ports - RX Initialization and Reset Ports
            i_GTRXRESET             = rx_init.gtrxreset,
            i_RXLPMRESET            = 0,
            i_RXOOBRESET            = 0,
            i_RXPCSRESET            = 0,
            i_RXPMARESET            = 0,

            # Receive Ports - RX OOB Signaling ports
            o_RXCOMSASDET           = Open(),
            o_RXCOMWAKEDET          = Open(),
            o_RXCOMINITDET          = Open(),
            o_RXELECIDLE            = self.rx_idle,
            i_RXELECIDLEMODE        = 0b00,

            # Receive Ports - RX Polarity Control Ports
            i_RXPOLARITY            = rx_polarity,

            # Receive Ports -RX Initialization and Reset Ports
            o_RXRESETDONE           = rx_init.rxresetdone,

            # TX Buffer Bypass Ports
            i_TXPHDLYTSTCLK         = 0,

            # TX Configurable Driver Ports
            i_TXPOSTCURSOR          = 0b00000,
            i_TXPOSTCURSORINV       = 0,
            i_TXPRECURSOR           = 0b00000,
            i_TXPRECURSORINV        = 0,

            # TX Fabric Clock Output Control Ports
            i_TXRATEMODE            = 0,

            # TX Initialization and Reset Ports
            i_CFGRESET              = 0,
            i_GTTXRESET             = tx_init.gttxreset,
            o_PCSRSVDOUT            = Open(),
            i_TXUSERRDY             = tx_init.txuserrdy,

            # TX Phase Interpolator PPM Controller Ports
            i_TXPIPPMEN             = 0,
            i_TXPIPPMOVRDEN         = 0,
            i_TXPIPPMPD             = 0,
            i_TXPIPPMSEL            = 1,
            i_TXPIPPMSTEPSIZE       = 0,

            # Transceiver Reset Mode Operation
            i_GTRESETSEL            = 0,
            i_RESETOVRD             = 0,

            # Transmit Ports
            o_TXPMARESETDONE       = Open(),

            # Transmit Ports - Configurable Driver Ports
            i_PMARSVDIN0            = 0b0,
            i_PMARSVDIN1            = 0b0,

            # Transmit Ports - FPGA TX Interface Ports
            i_TXDATA                = tx_data,
            i_TXUSRCLK              = ClockSignal("tx"),
            i_TXUSRCLK2             = ClockSignal("tx"),

            # Transmit Ports - PCI Express Ports
            i_TXELECIDLE            = self.tx_idle,
            i_TXMARGIN              = 0,
            i_TXRATE                = 0,
            i_TXSWING               = 0,

            # Transmit Ports - Pattern Generator Ports
            i_TXPRBSFORCEERR        = 0,

            # Transmit Ports - TX 8B/10B Encoder Ports
            i_TX8B10BBYPASS         = 0,
            i_TXCHARDISPMODE        = 0,
            i_TXCHARDISPVAL         = 0,
            i_TXCHARISK             = tx_ctrl,

            # Transmit Ports - TX Buffer Bypass Ports
            i_TXDLYBYPASS           = 1,
            i_TXDLYEN               = tx_init.txdlyen,
            i_TXDLYHOLD             = 0,
            i_TXDLYOVRDEN           = 0,
            i_TXDLYSRESET           = tx_init.txdlysreset,
            o_TXDLYSRESETDONE       = tx_init.txdlysresetdone,
            i_TXDLYUPDOWN           = 0,
            i_TXPHALIGN             = tx_init.txphalign,
            o_TXPHALIGNDONE         = tx_init.txphaligndone,
            i_TXPHALIGNEN           = 0,
            i_TXPHDLYPD             = 0,
            i_TXPHDLYRESET          = 0,
            i_TXPHINIT              = tx_init.txphinit,
            o_TXPHINITDONE          = tx_init.txphinitdone,
            i_TXPHOVRDEN            = 0,

            # Transmit Ports - TX Buffer Ports
            o_TXBUFSTATUS           = Open(2),

            # Transmit Ports - TX Buffer and Phase Alignment Ports
            i_TXSYNCALLIN           = 0,
            o_TXSYNCDONE            = Open(),
            i_TXSYNCIN              = 0,
            i_TXSYNCMODE            = 0,
            o_TXSYNCOUT             = Open(),

            # Transmit Ports - TX Configurable Driver Ports
            o_GTPTXN                = self._tx_pads.n,
            o_GTPTXP                = self._tx_pads.p,
            i_TXBUFDIFFCTRL         = 0b100,
            i_TXDEEMPH              = 0,
            i_TXDIFFCTRL            = 0b1000,
            i_TXDIFFPD              = 0,
            i_TXINHIBIT             = self.tx_inhibit | tx_gpio_en,
            i_TXMAINCURSOR          = 0b0000000,
            i_TXPISOPD              = 0,

            # Transmit Ports - TX Fabric Clock Output Control Ports
            o_TXOUTCLK              = self.txoutclk,
            o_TXOUTCLKFABRIC        = Open(),
            o_TXOUTCLKPCS           = Open(),
            i_TXOUTCLKSEL           = 0b010,
            o_TXRATEDONE            = Open(),

            # Transmit Ports - TX Gearbox Ports
            o_TXGEARBOXREADY        = Open(),
            i_TXHEADER              = 0,
            i_TXSEQUENCE            = 0,
            i_TXSTARTSEQ            = 0,

            # Transmit Ports - TX Initialization and Reset Ports
            i_TXPCSRESET            = 0,
            i_TXPMARESET            = 0,
            o_TXRESETDONE           = tx_init.txresetdone,

            # Transmit Ports - TX OOB signalling Ports
            o_TXCOMFINISH           = Open(),
            i_TXCOMINIT             = 0,
            i_TXCOMSAS              = 0,
            i_TXCOMWAKE             = 0,
            i_TXPDELECIDLEMODE      = 0,

            # Transmit Ports - TX Polarity Control Ports
            i_TXPOLARITY            = tx_polarity ^ (tx_gpio_en & tx_gpio),

            # Transmit Ports - TX Receiver Detection Ports
            i_TXDETECTRX            = 0,

            # Transmit Ports - pattern Generator Ports
            i_TXPRBSSEL             = 0,
        )

        #
        # TX clocking
        #
        tx_reset_deglitched = Signal()
        #tx_reset_deglitched.attr.add("no_retiming")
        m.d.ss += tx_reset_deglitched.eq(~tx_init.done)
        m.domains.tx = ClockDomain()

        m.submodules += Instance("BUFG",
            i_I = self.txoutclk,
            o_O = ClockSignal("tx")
        )
        m.submodules += ResetSynchronizer(tx_reset_deglitched, domain="tx")

        platform.add_clock_constraint(self.txoutclk, 250e6)

        #
        # RX clocking
        #
        rx_reset_deglitched = Signal()
        #rx_reset_deglitched.attr.add("no_retiming")
        m.d.tx += rx_reset_deglitched.eq(~rx_init.done)
        m.domains.rx = ClockDomain()
        m.submodules += [
            Instance("BUFG",
                i_I = self.rxoutclk,
                o_O = ClockSignal("rx")
            ),
            ResetSynchronizer(rx_reset_deglitched, domain="rx")
        ]

        platform.add_clock_constraint(self.rxoutclk, 250e6)

        #
        # Tx Datapath
        #

        # We're always ready to accept data, since our inner SerDes spews out data at a fixed rate.
        m.d.comb += self.sink.ready.eq(1)

        # ... and provide that data to the SerDes' transmitter.
        m.d.comb += [
            tx_data           .eq(self.sink.data),
            tx_ctrl           .eq(self.sink.ctrl),
        ]


        #
        # Rx Datapath
        #

        # We're always grabbing data, so our output should always be valid.
        # (Decoding errors are still valid stream words; but are replaced with SUB).
        m.d.comb += self.source.valid.eq(1)

        # ... and then assign their values to our output bus.
        for i in range(nwords):

            # If 8B10B decoding failed on the given byte, replace it with our substitution character.
            with m.If(rx_code_error[i]):
                m.d.comb += [
                    self.source.data.word_select(i, 8)  .eq(SUB.value),
                    self.source.ctrl[i]                 .eq(SUB.ctrl),
                ]

            # Otherwise, pass it through directly.
            with m.Else():
                m.d.comb += [
                    self.source.data.word_select(i, 8)  .eq(rx_data.word_select(i, 8)),
                    self.source.ctrl[i]                 .eq(rx_ctrl[i])
                ]

        return m



class LunaArtix7SerDes(Elaboratable):
    def __init__(self, ss_clock_frequency, refclk_pads, refclk_frequency, tx_pads, rx_pads):
        """ Wrapper around the core Artix7 SerDes that optimizes the SerDes for USB3 use. """

        self._ss_clock_frequency = ss_clock_frequency
        self._refclk_pads        = refclk_pads
        self._refclk_frequency   = refclk_frequency
        self._tx_pads            = tx_pads
        self._rx_pads            = rx_pads

        #
        # I/O port
        #
        self.sink                    = USBRawSuperSpeedStream()
        self.source                  = USBRawSuperSpeedStream()

        self.reset                   = Signal()
        self.enable                  = Signal(reset=1) # i
        self.ready                   = Signal()        # o

        self.tx_polarity             = Signal()   # i
        self.tx_idle                 = Signal()   # i
        self.tx_pattern              = Signal(20) # i

        self.rx_polarity             = Signal()   # i
        self.rx_idle                 = Signal()   # o
        self.rx_align                = Signal(reset=1)   # i
        self.rx_termination          = Signal()   # i
        self.rx_eq_training          = Signal()   # i

        self.send_lfps_signaling     = Signal()
        self.lfps_signaling_detected = Signal()

        # Debug interface.
        self.alignment_offset        = Signal(2)
        self.raw_rx_data             = Signal(16)
        self.raw_rx_ctrl             = Signal(2)


    def elaborate(self, platform):
        m = Module()

        #
        # Clock
        #
        if isinstance(self._refclk_pads, (Signal, ClockSignal)):
            refclk = self._refclk_pads
        else:
            refclk = Signal()
            m.submodules += [
                Instance("IBUFDS_GTE2",
                    i_CEB=0,
                    i_I=self._refclk_pads.p,
                    i_IB=self._refclk_pads.n,
                    o_O=refclk
                )
            ]

        #
        # PLL
        #
        m.submodules.qpll = qpll = GTPQuadPLL(refclk, self._refclk_frequency, 5e9)


        #
        # Core Serdes
        #
        m.submodules.serdes = serdes = self.serdes = GTP(
            qpll               = qpll,
            tx_pads            = self._tx_pads,
            rx_pads            = self._rx_pads,
            ss_clock_frequency = self._ss_clock_frequency
        )
        m.d.comb += [
            serdes.reset.eq(self.reset),
            self.ready.eq(serdes.tx_ready & serdes.rx_ready),
        ]


        #
        # Transmit datapath.
        #
        m.submodules.tx_datapath = tx_datapath = TransmitPreprocessing()
        m.d.comb += [
            serdes.tx_idle             .eq(self.tx_idle),
            serdes.tx_enable           .eq(self.enable),
            serdes.tx_polarity         .eq(self.tx_polarity),

            tx_datapath.sink           .stream_eq(self.sink, endian_swap=True),
            serdes.sink                .stream_eq(tx_datapath.source),
        ]


        #
        # Receive datapath.
        #
        m.submodules.rx_datapath = rx_datapath = ReceivePostprocessing()
        m.d.comb += [
            self.rx_idle                  .eq(serdes.rx_idle),

            serdes.rx_enable              .eq(self.enable),
            serdes.rx_polarity            .eq(self.rx_polarity),
            serdes.rx_termination         .eq(self.rx_termination),
            serdes.rx_align               .eq(self.rx_align),
            rx_datapath.align             .eq(self.rx_align),
            serdes.train_equalizer        .eq(self.rx_eq_training),

            rx_datapath.sink              .stream_eq(serdes.source),
            self.source                   .stream_eq(rx_datapath.source, endian_swap=True),

            # XXX
            self.alignment_offset   .eq(rx_datapath.alignment_offset)
        ]


        #
        # LFPS Generation & Detection
        #
        m.submodules.lfps_generator = lfps_generator = LFPSSquareWaveGenerator(250e6, 25e6)
        m.d.comb += [
            serdes.tx_gpio_en             .eq(lfps_generator.tx_gpio_en),
            serdes.tx_gpio                .eq(lfps_generator.tx_gpio),
            lfps_generator.generate       .eq(self.send_lfps_signaling),

            self.lfps_signaling_detected  .eq(~serdes.rx_idle)
        ]

        return m
