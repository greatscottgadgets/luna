#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from nmigen import *

from ...stream  import USBRawSuperSpeedStream
from ..physical.coding import IDL

from .idle         import IdleHandshakeHandler
from .ltssm        import LTSSMController
from .command      import LinkCommandDetector
from .ordered_sets import TSTransceiver


class USB3LinkLayer(Elaboratable):
    """ Abstraction encapsulating the USB3 link layer hardware.

    Performs the lower-level data manipulations associated with transporting USB3 packets
    from place to place.

    """

    def __init__(self, *, physical_layer, ss_clock_frequency=125e6):
        self._physical_layer  = physical_layer
        self._clock_frequency = ss_clock_frequency

        #
        # I/O port
        #
        self.sink                  = USBRawSuperSpeedStream()
        self.source                = USBRawSuperSpeedStream()

        # Status signals.
        self.trained               = Signal()

        # Debug / status signals.  = Signal()
        self.in_training           = Signal()
        self.sending_ts1s          = Signal()
        self.sending_ts2s          = Signal()


    def elaborate(self, platform):
        m = Module()
        physical_layer = self._physical_layer

        # Mark ourselves as always consuming physical-layer packets.
        m.d.comb += physical_layer.source.ready.eq(1)

        #
        # Training Set Detectors/Emitters
        #
        m.submodules.ts = ts = TSTransceiver()
        m.d.comb += ts.sink.stream_eq(physical_layer.source, omit={"ready"}, endian_swap=True),


        #
        # Idle handshake / logical idle detection.
        #
        m.submodules.idle = idle = IdleHandshakeHandler()
        m.d.comb += idle.sink.stream_eq(physical_layer.source, omit={'ready'})


        #
        # Link Training and Status State Machine (LTSSM)
        #
        m.submodules.ltssm = ltssm = LTSSMController(ss_clock_frequency=self._clock_frequency)
        m.d.comb += [
            ltssm.phy_ready                    .eq(physical_layer.ready),

            # Power control.
            physical_layer.power_state         .eq(ltssm.power_state),
            ltssm.power_transition_complete    .eq(physical_layer.power_transition_complete),

            # TODO: detect LPFS warm reset signaling
            ltssm.in_usb_reset                 .eq(0),

            # Pass down our link controls to the physical layer.
            physical_layer.tx_electrical_idle  .eq(ltssm.tx_electrical_idle),
            physical_layer.engage_terminations .eq(ltssm.engage_terminations),

            # LFPS control.
            ltssm.lfps_polling_detected        .eq(physical_layer.lfps_polling_detected),
            physical_layer.send_lfps_polling   .eq(ltssm.send_lfps_polling),
            ltssm.lfps_cycles_sent             .eq(physical_layer.lfps_cycles_sent),

            # Training set detectors
            ltssm.ts1_detected                 .eq(ts.ts1_detected),
            ltssm.inverted_ts1_detected        .eq(ts.inverted_ts1_detected),
            ltssm.ts2_detected                 .eq(ts.ts2_detected),

            # Training set emitters
            ts.send_tseq_burst                 .eq(ltssm.send_tseq_burst),
            ts.send_ts1_burst                  .eq(ltssm.send_ts1_burst),
            ts.send_ts2_burst                  .eq(ltssm.send_ts2_burst),
            ltssm.ts_burst_complete            .eq(ts.burst_complete),

            # Scrambling control.
            physical_layer.enable_scrambling   .eq(ltssm.enable_scrambling),

            # Idle detection.
            ltssm.logical_idle_detected        .eq(1 | idle.idle_detected),

            # Status signaling.
            self.trained                      .eq(ltssm.link_ready),
            self.in_training                  .eq(ltssm.send_tseq_burst | ltssm.send_ts1_burst | ltssm.send_ts2_burst)
        ]

        #
        # Link command handling.
        #
        m.submodules.lc_receiver = lc_receiver = LinkCommandDetector()
        m.d.comb += [
            lc_receiver.sink  .stream_eq(physical_layer.source, omit={'ready'})
        ]


        #
        # SerDes transmit stream selection.
        #

        # If we're transmitting training sets, pass those to the physical layer.
        with m.If(ts.transmitting & ~ltssm.link_ready):
            m.d.comb += physical_layer.sink.stream_eq(ts.source, endian_swap=True)

        # Otherwise, if we have valid data to transmit, pass that along.
        with m.Elif(self.sink.valid):
            m.d.comb += physical_layer.sink.stream_eq(self.sink)

        # Otherwise, always generate logical idle symbols.
        with m.Else():
            m.d.comb += [
                physical_layer.sink.valid.eq(1),
                physical_layer.sink.data.eq(IDL.value),
                physical_layer.sink.ctrl.eq(0),
            ]

        #
        # Debugging
        #
        m.d.comb += [
            self.sending_ts1s.eq(ltssm.send_ts1_burst),
            self.sending_ts2s.eq(ltssm.send_ts2_burst)
        ]


        return m
