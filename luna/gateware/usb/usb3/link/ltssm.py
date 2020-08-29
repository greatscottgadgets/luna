#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based on ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Link Training and Status State Machine (LTSSM) handling. """

#
# WARNING: This implementation is currently the minimum set of things that make
# the SerDes PHY work in some cases. This is not a complete design.
#


from nmigen import *
from nmigen.lib.coding import Encoder


# FIXME: remove this
from ....interface.serdes_phy.utils import WaitTimer


class LTSSMController(Elaboratable):
    """ LTSSM Polling sub-FSM.

    Implements the Polling.* states of the USB3 LTSSM FSM [USB 3.2r1; section 7.5.4].

    """

    def __init__(self, sys_clk_freq, with_timers=True):
        self._clock_frequency = sys_clk_freq
        self._with_timers     = with_timers


        #
        # I/O port.
        #

        self.idle                  = Signal()
        self.rx_ready              = Signal()
        self.tx_ready              = Signal()
        self.exit_to_compliance    = Signal()
        self.exit_to_rx_detect     = Signal()

        self.rx_polarity           = Signal()
        self.train_alignment       = Signal()

        # LFPS detection / emission.
        self.lfps_polling_detected = Signal()
        self.send_lfps_polling     = Signal()

        # Training set detection signals.
        self.tseq_detected         = Signal()
        self.ts1_detected          = Signal()
        self.inverted_ts1_detected = Signal()
        self.ts2_detected          = Signal()

        # Training set generation signals.
        self.send_tseq_burst       = Signal()
        self.send_ts1_burst        = Signal()
        self.send_ts2_burst        = Signal()
        self.ts_burst_complete     = Signal()



    def elaborate(self, platform):
        m = Module()

        tx_lfps_count = Signal(16)
        rx_lfps_seen  = Signal()

        # Status of our
        tseq_seen     = Signal()
        ts1_seen      = Signal()
        inv_ts1_seen  = Signal()
        ts2_seen      = Signal()

        # 360ms Timer ------------------------------------------------------------------------------
        _360_ms_timer = WaitTimer(int(360e-3*self._clock_frequency))
        m.submodules += _360_ms_timer

        # 12ms Timer -------------------------------------------------------------------------------
        _12_ms_timer = WaitTimer(int(12e-3*self._clock_frequency))
        m.submodules += _12_ms_timer

        #
        # Asynchronous Test Sequence Detectors
        #
        with m.If(self.tseq_detected):
            m.d.ss += tseq_seen.eq(1)
        with m.If(self.ts1_detected):
            m.d.ss += ts1_seen.eq(1)
        with m.If(self.inverted_ts1_detected):
            m.d.ss += inv_ts1_seen.eq(1)
        with m.If(self.ts2_detected):
            m.d.ss += ts2_seen.eq(1)


        #
        # Alignment training.
        # Allow the device's LSM to change alignment until we've received enough TSEQs
        # to believe we have a lock going.
        #
        m.d.comb += self.train_alignment.eq(~tseq_seen)


        # XXX: debug
        #led = platform.request("rgb_led", 3)
        #m.d.comb += [
        #    led.b.eq(tseq_seen),
        #    led.r.eq(ts1_seen),
        #]

        #with m.If(self.lfps_polling_detected):
        #    m.d.ss += led.g.eq(1)

        #m.submodules.enc = enc = Encoder(8)
        #leds = Cat(platform.request("led", i, dir="o").o for i in range(3))
        #m.d.comb += [
        #    leds.eq(enc.o),
        #    platform.request("led", 3, dir="o").o.eq(enc.n)
        #]


        with m.FSM(domain="ss") as fsm:
            #m.d.comb += [
            #    enc.i[0].eq(fsm.ongoing("Polling.Entry")),
            #    enc.i[1].eq(fsm.ongoing("Polling.LFPS")),
            #    enc.i[2].eq(fsm.ongoing("Polling.RxEQ")),
            #    enc.i[3].eq(fsm.ongoing("Polling.Active")),
            #    enc.i[4].eq(fsm.ongoing("Polling.Configuration")),
            #    enc.i[5].eq(fsm.ongoing("Polling.Idle")),
            #    enc.i[6].eq(fsm.ongoing("Polling.ExitToCompliance")),
            #    enc.i[7].eq(fsm.ongoing("Polling.ExitToRxDetect")),
            #]
            #led = platform.request("rgb_led", 0)
            #m.d.comb += [
            #    led.r.eq(fsm.ongoing("Polling.LFPS")),
            #    led.g.eq(fsm.ongoing("Polling.RxEQ")),
            #    led.b.eq(fsm.ongoing("Polling.Active")),
            #]
            #led = platform.request("rgb_led", 1)
            #m.d.comb += [
            #    led.r.eq(fsm.ongoing("Polling.Configuration")),
            #    led.g.eq(fsm.ongoing("Polling.Idle")),
            #    led.b.eq(fsm.ongoing("Polling.Entry")),
            #]
            #led = platform.request("rgb_led", 2)
            #m.d.comb += [
            #    led.r.eq(fsm.ongoing("Polling.Configuration")),
            #    led.g.eq(fsm.ongoing("Polling.ExitToCompliance")),
            #    led.b.eq(fsm.ongoing("Polling.ExitToRxDetect")),
            #]


            # Polling.Entry -- we've just entered the Polling sub-FSM; which means that we've
            # just detected that there's a receiver on the far end of the SuperSpeed link.
            with m.State("Polling.Entry"):
                # Initialize our detection status...
                m.d.ss += [
                    tx_lfps_count  .eq(16),
                    rx_lfps_seen   .eq(0),
                    ts2_seen       .eq(0),
                ]

                # ... and immediately move into the LFPS state, where we'll attempt to exchange
                # LFPS polling messages with the other side of our link.
                m.next = "Polling.LFPS"

            # Polling.LFPS -- now that we know there's someone listening on the other side, we'll
            # begin exchanging LFPS messages; giving the two sides the opportunity to sync up and
            # establish initial DC characteristics. [USB 3.2r1: 7.5.4.3]
            with m.State("Polling.LFPS"):
                m.d.comb += [
                    _360_ms_timer.wait   .eq(self._with_timers),
                    _12_ms_timer.wait    .eq(1),

                    # Begin emitting our LFPS polling waveform...
                    self.send_lfps_polling .eq(1),
                ]

                with m.If(self.lfps_polling_detected):

                    # Clear all record of seen test sets.
                    m.d.ss += [
                        tseq_seen     .eq(0),
                        ts1_seen      .eq(0),
                        inv_ts1_seen  .eq(0),
                        ts2_seen      .eq(0)
                    ]
                    m.next = "Polling.RxEQ"


                ## Go to ExitToCompliance when:
                ## - 360ms timer is expired.
                with m.If(_360_ms_timer.done):
                    m.next = "Polling.ExitToCompliance"


                ### Go to RxEQ when:
                ### - at least 16 LFPS Polling Bursts have been generated.
                ### - 2 consecutive LFPS Polling Bursts have been received (ensured by ts_unit).
                ### - 4 LFPS Polling Bursts have been sent since first LFPS Polling Bursts reception.
                #with m.Elif(self._lfps.tx_count >= tx_lfps_count):

                #    with m.If(self._lfps.rx_polling & ~rx_lfps_seen):
                #        m.d.ss += [
                #            rx_lfps_seen   .eq(1),
                #            tx_lfps_count  .eq(self._lfps.tx_count + 4)
                #        ]

                #        m.d.ss += [
                #            tseq_seen     .eq(0),
                #            ts1_seen      .eq(0),
                #            inv_ts1_seen  .eq(0),
                #            ts2_seen      .eq(0)
                #        ]

                #    with m.If(rx_lfps_seen):
                #        m.next = "Polling.RxEQ"

            # Polling.RxEQ -- We've now seen the other side of our link, and are ready to initialize
            # communications. We'll bring our link online, and start sending our first Training Set (TSEQ).
            # [USB 3.2.r1: 7.5.4.7]
            with m.State("Polling.RxEQ"):
                m.d.comb += [
                    self.send_tseq_burst  .eq(1),
                ]

                # Go to Active when the 65536 TSEQ ordered sets are sent.
                # FIXME: handle failed alignment?
                with m.If(self.ts_burst_complete):
                    m.next = "Polling.Active"


            # Polling.Active -- We've now exchanged our initial test sequences, and we're ready to
            # begin exchaning our core training sequences (TS1/TS2). We'll start sending TS1, and wait
            # to see the same thing from the host. [USB 3.2r1: 7.5.4.8]
            with m.State("Polling.Active"):
                m.d.comb += [
                    _12_ms_timer.wait    .eq(self._with_timers),
                    self.send_ts1_burst  .eq(1)
                ]

                # Go to RxDetect if no TS1/TS2 seen in the 12ms.
                with m.If(_12_ms_timer.done):
                    m.next = "Polling.ExitToRxDetect"

                # Once we've seen at least eight consecutive TS1s from the host, we're ready to move on
                # with link training, and we know our polarity isn't inverted.
                with m.If(ts1_seen):
                    m.d.comb += _12_ms_timer.wait.eq(0)
                    m.d.ss   += [
                        self.rx_polarity .eq(0),
                        #ts2_seen         .eq(0),
                    ]
                    m.next = "Polling.Configuration"

                # If we see eight consecutive values equal to the logical inverse of TS1, it looks like
                # we have a logically inverted link. We'll ask our SerDes to invert any received data,
                # and move on as if we'd received eight TS1s.
                with m.If(inv_ts1_seen):
                    m.d.comb += _12_ms_timer.wait.eq(0)
                    m.d.ss   += [
                        self.rx_polarity .eq(1),
                        #ts2_seen  .eq(0),
                    ]
                    m.next = "Polling.Configuration"

            # Polling.Configuration --
            with m.State("Polling.Configuration"):
                m.d.comb += [
                    _12_ms_timer.wait     .eq(self._with_timers),
                    self.send_ts2_burst   .eq(1),
                    self.rx_ready         .eq(ts2_seen),
                ]


                # Go to RxDetect if no TS2 seen in the 12ms.
                with m.If(_12_ms_timer.done):
                    m.d.comb += _12_ms_timer.wait.eq(0)
                    m.next = "Polling.ExitToRxDetect"

                # Go to Idle when:
                # - 8 consecutive TS2 ordered sets are received. (8 ensured by ts_unit)
                # - 16 TS2 ordered sets are sent after receiving the first 8 TS2 ordered sets. FIXME
                with m.If(self.ts_burst_complete):
                    with m.If(ts2_seen):
                        m.next = "Polling.Idle"


            # Polling.Idle --
            with m.State("Polling.Idle"):
                m.d.comb += [
                    self.idle.eq(1),
                    self.rx_ready.eq(1),
                    self.tx_ready.eq(1),
                ]
                with m.If(self.ts1_detected): # FIXME: for bringup, should be Recovery.Active
                    m.next = "Polling.Active"
                with m.Elif(self.lfps_polling_detected):
                    m.next = "Polling.Entry"


            # Exit to Compliance --
            with m.State("Polling.ExitToCompliance"):
                m.d.comb += [
                    #self._lfps.tx_idle.eq(1), # FIXME: for bringup
                    self.exit_to_compliance.eq(1)
                ]
                with m.If(self.lfps_polling_detected): # FIXME: for bringup
                    m.next = "Polling.Entry"

            # Exit to RxDetect
            with m.State("Polling.ExitToRxDetect"):
                m.d.comb += [
                    #self._lfps.tx_idle.eq(1),     # FIXME: for bringup
                    self.exit_to_rx_detect.eq(1)
                ]

                with m.If(self.lfps_polling_detected): # FIXME: for bringup
                    m.next = "Polling.Entry"

        return m
