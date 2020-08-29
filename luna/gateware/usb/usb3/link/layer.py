#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from nmigen import *

from ...stream  import USBRawSuperSpeedStream

from .ltssm        import LTSSMController
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



    def elaborate(self, platform):
        m = Module()
        physical_layer = self._physical_layer

        #
        # Training Set Detectors/Emitters
        #
        m.submodules.ts = ts = TSTransceiver()
        m.d.comb += ts.sink.stream_eq(physical_layer.source, omit={"ready"}),


        #
        # Link Training and Status State Machine (LTSSM)
        #
        m.submodules.ltssm = ltssm = LTSSMController(sys_clk_freq=self._clock_frequency, with_timers=False)
        m.d.comb += [
            physical_layer.train_alignment    .eq(ltssm.train_alignment),

            # LFPS control.
            ltssm.lfps_polling_detected       .eq(physical_layer.lfps_polling_detected),
            physical_layer.send_lfps_polling  .eq(ltssm.send_lfps_polling),

            # Training set detectors
            ltssm.tseq_detected               .eq(ts.tseq_detected),
            ltssm.ts1_detected                .eq(ts.ts1_detected),
            ltssm.inverted_ts1_detected       .eq(ts.inverted_ts1_detected),
            ltssm.ts2_detected                .eq(ts.ts2_detected),

            # Training set emitters
            ts.send_tseq_burst                .eq(ltssm.send_tseq_burst),
            ts.send_ts1_burst                 .eq(ltssm.send_ts1_burst),
            ts.send_ts2_burst                 .eq(ltssm.send_ts2_burst),
            ltssm.ts_burst_complete           .eq(ts.burst_complete)
        ]


        #
        # SerDes transmit stream selection.
        #
        with m.If(ts.transmitting):
            m.d.comb += physical_layer.sink.stream_eq(ts.source)
        with m.Else():
            m.d.comb += physical_layer.sink.stream_eq(self.source)


        return m
