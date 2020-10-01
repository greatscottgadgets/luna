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
from .command      import LinkCommandDetector, LinkCommandGenerator
from .ordered_sets import TSTransceiver
from .bringup      import LinkBringupSequencer
from .header       import HeaderPacketReceiver

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

        # Debug output.
        self.debug_event           = Signal()


    def elaborate(self, platform):
        m = Module()
        physical_layer = self._physical_layer

        # Mark ourselves as always consuming physical-layer packets.
        m.d.comb += physical_layer.source.ready.eq(1)

        #
        # Training Set Detectors/Emitters
        #
        m.submodules.ts = ts = TSTransceiver()
        m.d.comb += ts.sink.tap(physical_layer.source, endian_swap=True),


        #
        # Idle handshake / logical idle detection.
        #
        m.submodules.idle = idle = IdleHandshakeHandler()
        m.d.comb += idle.sink.tap(physical_layer.source)


        #
        # Link Training and Status State Machine (LTSSM)
        #
        m.submodules.ltssm = ltssm = LTSSMController(ss_clock_frequency=self._clock_frequency)
        m.d.comb += [
            ltssm.phy_ready                      .eq(physical_layer.ready),

            # For now, we'll consider ourselves in USB reset iff we detect reset signaling.
            # This should be expanded; ideally to also consider e.g. loss of VBUS on some devices.
            #ltssm.in_usb_reset                   .eq(physical_layer.lfps_reset_detected),

            # Link Partner Detection
            physical_layer.perform_rx_detection  .eq(ltssm.perform_rx_detection),
            ltssm.link_partner_detected          .eq(physical_layer.link_partner_detected),
            ltssm.no_link_partner_detected       .eq(physical_layer.no_link_partner_detected),

            # Pass down our link controls to the physical layer.
            physical_layer.tx_electrical_idle    .eq(ltssm.tx_electrical_idle),
            physical_layer.engage_terminations   .eq(ltssm.engage_terminations),

            # LFPS control.
            ltssm.lfps_polling_detected          .eq(physical_layer.lfps_polling_detected),
            physical_layer.send_lfps_polling     .eq(ltssm.send_lfps_polling),
            ltssm.lfps_cycles_sent               .eq(physical_layer.lfps_cycles_sent),

            # Training set detectors
            ltssm.ts1_detected                   .eq(ts.ts1_detected),
            ltssm.inverted_ts1_detected          .eq(ts.inverted_ts1_detected),
            ltssm.ts2_detected                   .eq(ts.ts2_detected),

            # Training set emitters
            ts.send_tseq_burst                   .eq(ltssm.send_tseq_burst),
            ts.send_ts1_burst                    .eq(ltssm.send_ts1_burst),
            ts.send_ts2_burst                    .eq(ltssm.send_ts2_burst),
            ltssm.ts_burst_complete              .eq(ts.burst_complete),

            # Scrambling control.
            physical_layer.enable_scrambling     .eq(ltssm.enable_scrambling),

            # Idle detection.
            idle.enable                          .eq(ltssm.perform_idle_handshake),
            ltssm.idle_handshake_complete        .eq(idle.idle_handshake_complete),

            # Status signaling.
            self.trained                         .eq(ltssm.link_ready)
        ]



        #
        # Link command handling.
        #

        # Link Command Receiver
        m.submodules.lc_detector = lc_detector = LinkCommandDetector()
        m.d.comb += [
            lc_detector.sink  .tap(physical_layer.source)
        ]

        # Link Command Generator
        m.submodules.lc_generator = lc_generator = LinkCommandGenerator()


        #
        # Link Bringup.
        #
        m.submodules.bringup = bringup = LinkBringupSequencer()
        m.d.comb += [
            bringup.entering_u0        .eq(ltssm.entering_u0),

            lc_generator.bus_idle      .eq(ltssm.link_ready),
            lc_generator.generate      .eq(bringup.request_link_command),
            lc_generator.command       .eq(bringup.link_command),
            lc_generator.subtype       .eq(bringup.link_command_subtype),

            bringup.link_command_done  .eq(lc_generator.done)
        ]

        #
        # Header Packet Rx Path
        #
        m.submodules.header_rx = header_rx = HeaderPacketReceiver()
        m.d.comb += [
            header_rx.sink    .tap(physical_layer.source),
            self.debug_event  .eq(header_rx.new_packet)
        ]


        #
        # PHY transmit stream selection.
        #

        # If we're transmitting training sets, pass those to the physical layer.
        with m.If(ts.transmitting & ~ltssm.link_ready):
            m.d.comb += physical_layer.sink.stream_eq(ts.source, endian_swap=True)

        # If we're transmitting a link command, pass that to the physical layer.
        with m.Elif(lc_generator.source.valid):
            m.d.comb += physical_layer.sink.stream_eq(lc_generator.source)

        # Otherwise, if we have valid data to transmit, pass that along.
        with m.Elif(self.sink.valid):
            m.d.comb += physical_layer.sink.stream_eq(self.sink)

        # Otherwise, always generate logical idle signaling.
        with m.Else():
            m.d.comb += [

                # Drive our physical layer with our IDL value (0x00)...
                physical_layer.sink.valid    .eq(1),
                physical_layer.sink.data     .eq(IDL.value),
                physical_layer.sink.ctrl     .eq(IDL.ctrl),

                # ... and let the physical layer know it can insert CTC skips.
                physical_layer.can_send_skp  .eq(1)
            ]

        return m
