#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from nmigen import *

from ...stream  import USBRawSuperSpeedStream
from ..physical.coding import IDL


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
        m.d.comb += ts.sink.stream_eq(physical_layer.source, omit={"ready"}, endian_swap=True),


        #
        # Link Training and Status State Machine (LTSSM)
        #
        m.submodules.ltssm = ltssm = LTSSMController(ss_clock_frequency=self._clock_frequency)
        m.d.comb += [

            # For now, only recognize a power-on-reset. Eventually, this should also include
            # detecting LFPS warm-reset signaling.
            ltssm.in_usb_reset                .eq(~physical_layer.physical_layer_ready),

            # Pass down our link controls to the physical layer.
            physical_layer.enable_scrambling  .eq(ltssm.enable_scrambling),
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
            ltssm.ts_burst_complete           .eq(ts.burst_complete),

            # Scrambling control.
            physical_layer.enable_scrambling  .eq(ltssm.enable_scrambling),

            # Idle detection.
            # FIXME: actually detect idle
            ltssm.logical_idle_detected       .eq(1)
        ]


        #
        # SerDes transmit stream selection.
        #

        # If we're transmitting training sets, pass those to the physical layer.
        with m.If(ts.transmitting):
            m.d.comb += physical_layer.sink.stream_eq(ts.source, endian_swap=True)

        # Otherwise, if we have valid data to transmit, pass that along.
        with m.Elif(self.source.valid):
            m.d.comb += physical_layer.sink.stream_eq(self.source)

        # Otherwise, always generate logical idle symbols.
        with m.Else():
            m.d.comb += [
                physical_layer.sink.valid.eq(1),
                physical_layer.sink.data.eq(IDL.value),
                physical_layer.sink.ctrl.eq(0),
            ]


        return m
