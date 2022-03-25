#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 physical-layer abstraction."""

import logging

from amaranth import *
from amaranth.lib.fifo import AsyncFIFOBuffered
from ...stream  import USBRawSuperSpeedStream

from .lfps       import LFPSTransceiver
from .scrambling import Scrambler, Descrambler
from .power      import PHYResetController, LinkPartnerDetector
from .ctc        import CTCSkipInserter, CTCSkipRemover
from .alignment  import RxWordAligner, RxPacketAligner

class USB3PhysicalLayer(Elaboratable):
    """ Abstraction encapsulating the USB3 physical layer hardware.

    Performs the lowest-level PHY interfacing, including scrambling/descrambling.

    Attributes
    ----------
    sink: USBRawSuperSpeedStream(), input stream
        Data stream accepted from the Link layer; contains raw data to be transmitted.
    source: USBRawSuperSpeedStream(), output stream
        Data stream generated for transit to the Link layer; contains descrambled data accepted from the SerDes.

    enable_scrambling: Signal(), input
        When asserted, scrambling/descrambling will be enabled.
    """

    def __init__(self, *, phy, sync_frequency):
        self._phy = phy
        self._sync_frequency = sync_frequency

        #
        # I/O port
        #

        # Data streams.
        self.sink                       = USBRawSuperSpeedStream()
        self.source                     = USBRawSuperSpeedStream()

        # Raw source (never descrambled; for reset detection).
        self.raw_source                 = USBRawSuperSpeedStream()

        # Physical link state.
        self.ready                      = Signal()
        self.engage_terminations        = Signal()
        self.tx_electrical_idle         = Signal()
        self.invert_rx_polarity         = Signal()
        self.train_equalizer            = Signal()
        self.vbus_present               = Signal()

        # Scrambling control.
        self.enable_scrambling          = Signal()

        # Link partner detection.
        self.perform_rx_detection       = Signal()
        self.link_partner_detected      = Signal()
        self.no_link_partner_detected   = Signal()

        # LFPS control / detection.
        self.send_lfps_polling          = Signal()
        self.lfps_cycles_sent           = Signal(16)

        self.lfps_polling_detected      = Signal()
        self.lfps_reset_detected        = Signal()

        # SKP insertion control.
        self.can_send_skp               = Signal()
        self.skip_removed               = Signal()

        # Debug signaling.
        self.ctc_bytes_in_buffer        = Signal(range(9))
        self.alignment_offset           = Signal(range(4))


    def elaborate(self, platform):
        m = Module()
        phy = self._phy

        #
        # PHY reset & power management.
        #
        m.submodules.reset_controller = reset_controller = PHYResetController(sync_frequency=self._sync_frequency)
        m.d.comb += [
            phy.reset                       .eq(reset_controller.reset),
            reset_controller.phy_status     .eq(phy.phy_status),
            self.ready                      .eq(reset_controller.ready),
        ]


        #
        # PHY control signal handling.
        #
        m.d.comb += [
            # Use USB3.0 5Gbps signaling.
            phy.phy_mode                .eq(0b01),
            phy.rate                    .eq(1),

            # Use nominal half full elastic buffer mode.
            phy.elas_buf_mode           .eq(0),

            # Use default/normal signal thresholds.
            phy.tx_swing                .eq(0),
            phy.tx_margin               .eq(0b000),
            phy.tx_deemph               .eq(0b01),

            # Pass through our remaining control signals directly to the PHY.
            phy.rx_termination          .eq(self.engage_terminations),
            phy.rx_polarity             .eq(self.invert_rx_polarity),
            phy.rx_eq_training          .eq(self.train_equalizer),

            # Pass through our VBUS detected signal up to the link layer.
            self.vbus_present           .eq(phy.power_present)
        ]


        #
        # Link Partner Detection
        #
        m.submodules.rx_detect = rx_detect = LinkPartnerDetector()
        m.d.comb += [
            rx_detect.request_detection    .eq(self.perform_rx_detection),
            rx_detect.phy_status           .eq(phy.phy_status),
            rx_detect.rx_status            .eq(phy.rx_status),

            #self.link_partner_detected     .eq(rx_detect.new_result & rx_detect.partner_present),
            #self.no_link_partner_detected  .eq(rx_detect.new_result & ~rx_detect.partner_present)

            # FIXME: this is temporary; it speeds up partner detection, but isn't strictly correct.
            # (This incorrectly attempts to do link training on USB2 hosts, too).
            phy.power_down                  .eq(0),
            self.link_partner_detected      .eq(phy.power_present)
        ]


        #
        # Transmit output conditioning.
        #

        # Scramble our data before transmitting it, if scrambling is enabled.
        m.submodules.scrambler = scrambler = Scrambler(initial_value=0xffff)
        m.d.comb += [
            scrambler.enable      .eq(self.enable_scrambling),
            scrambler.sink        .stream_eq(self.sink, omit={'valid'}),
            scrambler.sink.valid  .eq(1)
        ]

        # Insert Clock Tolerance Compensation SKP ordered sets, where necessary.
        m.submodules.tx_ctc = tx_ctc = CTCSkipInserter()
        m.d.comb += [
            tx_ctc.sink           .stream_eq(scrambler.source),
            tx_ctc.can_send_skip  .eq(self.can_send_skp),

            scrambler.hold        .eq(tx_ctc.sending_skip)
        ]


        # Convert our Tx stream into PHY connections whenever we're not in electrical idle.
        with m.If(~self.tx_electrical_idle):
            m.d.comb += [
                phy.tx_data          .eq(tx_ctc.source.data),
                phy.tx_datak         .eq(tx_ctc.source.ctrl),
                tx_ctc.source.ready  .eq(1),
            ]


        #
        # Receive input conditioning.
        #

        # Clock tolerance compensation / SKP remover.
        m.submodules.rx_ctc = rx_ctc = CTCSkipRemover()
        m.d.comb += [
            # Connect our PHY's receive data directly to our CTC hardware.
            rx_ctc.sink.data   .eq(phy.rx_data),
            rx_ctc.sink.ctrl   .eq(phy.rx_datak),
            rx_ctc.sink.valid  .eq(1),

            # Diagnostic output.
            self.skip_removed         .eq(rx_ctc.skip_removed),
            self.ctc_bytes_in_buffer  .eq(rx_ctc.bytes_in_buffer),
        ]

        # Word align the data, so it's easily handleable internally.
        m.submodules.aligner = aligner = RxWordAligner()
        m.d.comb += [
            aligner.sink           .stream_eq(rx_ctc.source),
            self.raw_source        .tap(aligner.source),

            self.alignment_offset  .eq(aligner.alignment_offset)
        ]


        # De-scramble our data before output, if needed.
        m.submodules.descrambler = descrambler = Descrambler()
        m.d.comb += [
            descrambler.enable  .eq(self.enable_scrambling),
            descrambler.sink    .stream_eq(aligner.source),
        ]

        # Finally, as a requirement of strict compliance, we'll ensure we can handle packets
        # that arrive even without correct alignment.
        m.submodules.realigner = realigner = RxPacketAligner()
        m.d.comb += [
            realigner.sink      .stream_eq(descrambler.source),
            self.source         .stream_eq(realigner.source),
        ]


        #
        # LFPS signaling.
        #

        m.submodules.lfps_transciever = lfps = LFPSTransceiver()
        m.d.comb += [
            lfps.send_polling           .eq(self.send_lfps_polling),
            self.lfps_cycles_sent       .eq(lfps.cycles_sent),

            self.lfps_polling_detected  .eq(lfps.polling_detected),
            self.lfps_reset_detected    .eq(lfps.reset_detected),

            # The RX_ELECIDLE signal being de-asserted indicates we're receiving valid
            # LFPS signaling. [TUSB1310A: Table 3-3]
            lfps.signaling_received     .eq(~phy.rx_elec_idle),
        ]

        with m.Switch(phy.power_down):

            # In PO, we'll let the LTSSM control electrical idle, and pass through our signals
            # in a way that allows LTSSM.
            with m.Case(0):
                m.d.comb += [
                    # In P0, pass through TX_ELECIDLE directly, as it has its intended meaning.
                    phy.tx_elec_idle              .eq(lfps.drive_electrical_idle | self.tx_electrical_idle),

                    # In P0, the TX_DETRX_LPBK signal is used to drive an LFPS square wave onto the
                    # transmit line when we're in electrical idle, and places us into loopback
                    # otherwise. [TUSB1310A: Table 5-3]  Our LFPS generator takes care of this.
                    phy.tx_detrx_lpbk             .eq(lfps.send_signaling)
                ]

            # For now, we won't support LFPS from states other than P0, as our LTSSM only
            # performs it from P0. We'll use the PHY exclusively for receiver detection.
            with m.Default():
                m.d.comb += [
                    phy.tx_elec_idle              .eq(1),
                    phy.tx_detrx_lpbk             .eq(rx_detect.detection_control)
                ]

        return m
