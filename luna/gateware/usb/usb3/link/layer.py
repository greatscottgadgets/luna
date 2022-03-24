#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 link-layer abstraction."""

from amaranth import *

from ...stream          import USBRawSuperSpeedStream, SuperSpeedStreamArbiter, SuperSpeedStreamInterface
from ..physical.coding  import IDL

from .idle         import IdleHandshakeHandler
from .ltssm        import LTSSMController
from .header       import HeaderQueue, HeaderQueueArbiter
from .receiver     import HeaderPacketReceiver
from .transmitter  import PacketTransmitter
from .timers       import LinkMaintenanceTimers
from .ordered_sets import TSTransceiver
from .data         import DataPacketReceiver, DataPacketTransmitter, DataHeaderPacket


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

        # Header packet exchanges.
        self.header_sink               = HeaderQueue()
        self.header_source             = HeaderQueue()

        # Data packet exchange interface.
        self.data_source               = SuperSpeedStreamInterface()
        self.data_header_from_host     = DataHeaderPacket()
        self.data_source_complete      = Signal()
        self.data_source_invalid       = Signal()

        self.data_sink                 = SuperSpeedStreamInterface()
        self.data_sink_send_zlp        = Signal()
        self.data_sink_sequence_number = Signal(5)
        self.data_sink_endpoint_number = Signal(4)
        self.data_sink_length          = Signal(range(1024 + 1))
        self.data_sink_direction       = Signal()

        # Device state for header packets
        self.current_address           = Signal(7)

        # Status signals.
        self.trained                   = Signal()
        self.ready                     = Signal()
        self.in_reset                  = Signal()

        # Test and debug signals.
        self.disable_scrambling        = Signal()


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
            # Note: we bring the physical layer's "raw" (non-descrambled) source to the TS detector,
            # as we'll still need to detect non-scrambled TS1s and TS2s if they arrive during normal
            # operation.
            ts.sink              .tap(physical_layer.raw_source),
            training_set_source  .stream_eq(ts.source)
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
            ltssm.in_usb_reset                   .eq(physical_layer.lfps_reset_detected | ~physical_layer.vbus_present),

            # Link Partner Detection
            physical_layer.perform_rx_detection  .eq(ltssm.perform_rx_detection),
            ltssm.link_partner_detected          .eq(physical_layer.link_partner_detected),
            ltssm.no_link_partner_detected       .eq(physical_layer.no_link_partner_detected),

            # Pass down our link controls to the physical layer.
            physical_layer.tx_electrical_idle    .eq(ltssm.tx_electrical_idle),
            physical_layer.engage_terminations   .eq(ltssm.engage_terminations),
            physical_layer.invert_rx_polarity    .eq(ltssm.invert_rx_polarity),
            physical_layer.train_equalizer       .eq(ltssm.train_equalizer),

            # LFPS control.
            ltssm.lfps_polling_detected          .eq(physical_layer.lfps_polling_detected),
            physical_layer.send_lfps_polling     .eq(ltssm.send_lfps_polling),
            ltssm.lfps_cycles_sent               .eq(physical_layer.lfps_cycles_sent),

            # Training set detectors
            ltssm.tseq_detected                  .eq(ts.tseq_detected),
            ltssm.ts1_detected                   .eq(ts.ts1_detected),
            ltssm.inverted_ts1_detected          .eq(ts.inverted_ts1_detected),
            ltssm.ts2_detected                   .eq(ts.ts2_detected),
            ltssm.hot_reset_requested            .eq(ts.hot_reset_requested),
            ltssm.loopback_requested             .eq(ts.loopback_requested),
            ltssm.no_scrambling_requested        .eq(ts.no_scrambling_requested),

            # Training set emitters
            ts.send_tseq_burst                   .eq(ltssm.send_tseq_burst),
            ts.send_ts1_burst                    .eq(ltssm.send_ts1_burst),
            ts.send_ts2_burst                    .eq(ltssm.send_ts2_burst),
            ts.request_hot_reset                 .eq(ltssm.request_hot_reset),
            ts.request_no_scrambling             .eq(ltssm.request_no_scrambling),
            ltssm.ts_burst_complete              .eq(ts.burst_complete),

            # Scrambling control.
            physical_layer.enable_scrambling     .eq(ltssm.enable_scrambling),

            # Idle detection.
            idle.enable                          .eq(ltssm.perform_idle_handshake),
            ltssm.idle_handshake_complete        .eq(idle.idle_handshake_complete),

            # Link maintainance.
            timers.enable                        .eq(ltssm.link_ready),

            # Status signaling.
            self.trained                         .eq(ltssm.link_ready),
            self.in_reset                        .eq(ltssm.request_hot_reset | ltssm.in_usb_reset),

            # Test and debug.
            ltssm.disable_scrambling             .eq(self.disable_scrambling),
        ]


        #
        # Packet transmission path.
        # Accepts packets from the protocol and link layers, and transmits them.
        #

        # Transmit header multiplexer.
        m.submodules.hp_mux = hp_mux = HeaderQueueArbiter()
        hp_mux.add_producer(self.header_sink)

        # Core transmitter.
        m.submodules.transmitter = transmitter = PacketTransmitter()
        m.d.comb += [
            transmitter.sink                .tap(physical_layer.source),
            transmitter.enable              .eq(ltssm.link_ready),
            transmitter.usb_reset           .eq(self.in_reset),

            transmitter.queue               .header_eq(hp_mux.source),

            # Link state management handling.
            timers.link_command_received  .eq(transmitter.link_command_received),
            self.ready                    .eq(transmitter.bringup_complete),
        ]



        #
        # Header Packet Rx Path.
        # Receives header packets and forwards them up to the protocol layer.
        #
        m.submodules.header_rx = header_rx = HeaderPacketReceiver()
        m.d.comb += [
            header_rx.sink                   .tap(physical_layer.source),
            header_rx.enable                 .eq(ltssm.link_ready),
            header_rx.usb_reset              .eq(self.in_reset),

            # Bring our header packet interface to the protocol layer.
            self.header_source               .header_eq(header_rx.queue),

            # Keepalive handling.
            timers.link_command_transmitted  .eq(header_rx.source.valid),
            header_rx.keepalive_required     .eq(timers.schedule_keepalive),
            timers.packet_received           .eq(header_rx.packet_received),

            # Transmitter event path.
            header_rx.retry_required         .eq(transmitter.retry_required),
            transmitter.lrty_pending         .eq(header_rx.lrty_pending),
            header_rx.retry_received         .eq(transmitter.retry_received),

            # For now, we'll reject all forms of power management by sending a REJECT
            # whenever we receive an LGO (Link Go-to) request.
            header_rx.reject_power_state     .eq(transmitter.lgo_received),
        ]


        #
        # Link Recovery Control
        #
        m.d.comb += ltssm.trigger_link_recovery.eq(
            timers.transition_to_recovery |
            header_rx.recovery_required   |
            transmitter.recovery_required
        )

        #
        # Data packet handlers.
        #

        # Receiver.
        m.submodules.data_rx = data_rx = DataPacketReceiver()
        m.d.comb += [
            data_rx.sink                .tap(physical_layer.source),

            # Data interface to Protocol layer.
            self.data_source            .stream_eq(data_rx.source),
            self.data_header_from_host  .eq(data_rx.header),
            self.data_source_complete   .eq(data_rx.packet_good),
            self.data_source_invalid    .eq(data_rx.packet_bad),
        ]

        # Transmitter.
        m.submodules.data_tx = data_tx = DataPacketTransmitter()
        hp_mux.add_producer(data_tx.header_source)

        m.d.comb += [
            transmitter.data_sink    .stream_eq(data_tx.data_source),

            # Device state information.
            data_tx.address          .eq(self.current_address),

            # Data interface from Protocol layer.
            data_tx.data_sink        .stream_eq(self.data_sink),
            data_tx.send_zlp         .eq(self.data_sink_send_zlp),
            data_tx.sequence_number  .eq(self.data_sink_sequence_number),
            data_tx.endpoint_number  .eq(self.data_sink_endpoint_number),
            data_tx.data_length      .eq(self.data_sink_length),
            data_tx.direction        .eq(self.data_sink_direction)
        ]


        #
        # Transmit stream arbiter.
        #
        m.submodules.stream_arbiter = arbiter = SuperSpeedStreamArbiter()

        # Add each of our streams to our arbiter, from highest to lowest priority.
        arbiter.add_stream(training_set_source)
        arbiter.add_stream(header_rx.source)
        arbiter.add_stream(transmitter.source)

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
