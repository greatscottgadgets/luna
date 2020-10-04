#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from nmigen import *

from ...stream          import USBRawSuperSpeedStream, SuperSpeedStreamArbiter
from ..physical.coding  import IDL

from .idle         import IdleHandshakeHandler
from .ltssm        import LTSSMController
from .header       import HeaderQueue
from .header_rx    import HeaderPacketReceiver
from .header_tx    import HeaderPacketTransmitter
from .timers       import LinkMaintenanceTimers
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

        # Header packet exchanges.
        self.header_sink           = HeaderQueue()
        self.header_source         = HeaderQueue()

        # Status signals.
        self.trained               = Signal()
        self.ready                 = Signal()

        # Debug output.
        self.debug_event           = Signal()
        self.debug_misc            = Signal(32)


    def elaborate(self, platform):
        m = Module()
        physical_layer = self._physical_layer

        # Mark ourselves as always consuming physical-layer packets.
        m.d.comb += physical_layer.source.ready.eq(1)

        #
        # Training Set Detectors/Emitters
        #
        training_set_source = USBRawSuperSpeedStream()

        m.submodules.ts = ts = TSTransceiver()
        m.d.comb += [
            ts.sink               .tap(physical_layer.source, endian_swap=True),
            training_set_source  .stream_eq(ts.source, endian_swap=True)
        ]




        #
        # Idle handshake / logical idle detection.
        #
        m.submodules.idle = idle = IdleHandshakeHandler()
        m.d.comb += idle.sink.tap(physical_layer.source)


        #
        # U0 Maintenance Timers
        #
        m.submodules.timers = timers = LinkMaintenanceTimers(ss_clock_frequency=self._clock_frequency)


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

            # Link maintainance.
            timers.enable                        .eq(ltssm.link_ready),

            # Status signaling.
            self.trained                         .eq(ltssm.link_ready)
        ]


        #
        # Header Packet Tx Path.
        # Accepts header packets from the protocol layer, and transmits them.
        #
        m.submodules.header_tx = header_tx = HeaderPacketTransmitter()
        m.d.comb += [
            header_tx.sink                .tap(physical_layer.source),
            header_tx.enable              .eq(ltssm.link_ready),

            header_tx.queue               .header_eq(self.header_sink),

            # Link state management handling.
            timers.link_command_received  .eq(header_tx.link_command_received),
            self.ready                    .eq(header_tx.bringup_complete),

            # Debug output.
            self.debug_misc               .eq(header_tx.packets_to_send)
        ]



        #
        # Header Packet Rx Path.
        # Receives header packets and forwards them up to the protocol layer.
        #
        m.submodules.header_rx = header_rx = HeaderPacketReceiver()
        m.d.comb += [
            header_rx.sink                   .tap(physical_layer.source),
            header_rx.enable                 .eq(ltssm.link_ready),

            # Bring our header packet interface to the physical layer.
            self.header_source               .header_eq(header_rx.queue),

            # Keepalive handling.
            timers.link_command_transmitted  .eq(header_rx.source.valid),
            header_rx.keepalive_required     .eq(timers.schedule_keepalive),

            # Transmitter event path.
            header_rx.retry_received         .eq(header_tx.retry_received)
        ]


        #
        # Link Recovery Control
        #
        m.d.comb += [
            ltssm.trigger_link_recovery .eq(timers.transition_to_recovery | header_rx.recovery_required)
        ]


        #
        # Transmit stream arbiter.
        #
        m.submodules.stream_arbiter = arbiter = SuperSpeedStreamArbiter()

        # Add each of our streams to our arbiter, from highest to lowest priority.
        arbiter.add_stream(training_set_source)
        arbiter.add_stream(header_rx.source)
        arbiter.add_stream(header_tx.source)
        arbiter.add_stream(self.sink)

        # If we're idle, send logical idle.
        with m.If(arbiter.idle):
            m.d.comb += [
                # Drive our idle stream with our IDL value (0x00)...
                physical_layer.sink.valid    .eq(1),
                physical_layer.sink.data     .eq(IDL.value),
                physical_layer.sink.ctrl     .eq(IDL.ctrl),

                # Let the physical layer know it can insert CTC skips whenever data is being accepted
                # from our logical idle stream.
                physical_layer.can_send_skp  .eq(1)
            ]

        # Otherwise, output our stream data.
        with m.Else():
            m.d.comb += physical_layer.sink.stream_eq(arbiter.source)



        return m
