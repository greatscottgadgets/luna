#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import logging

from nmigen      import *

from ...usb.stream  import USBRawSuperSpeedStream
from .lfps          import LFPSTransceiver


class SerDesPHY(Elaboratable):
    """ USB3 SerDes-based PHY.

    Not yet compliant with PIPE; but will be.
    """
    def __init__(self, serdes, ss_clk_frequency, fast_clk_frequency, little_endian=True):
        assert ss_clk_frequency   >= 125e6
        assert fast_clk_frequency >= 200e6

        # TODO: remove when complete
        logging.warning("The SerDes-based USB3 PHY is not at all complete.")
        logging.warning("Do not expect -anything- to work!")

        self._serdes               = serdes
        self._clock_frequency      = ss_clk_frequency
        self._fast_clock_frequency = fast_clk_frequency
        self._little_endian        = little_endian

        #
        # I/O port
        #
        self.ready  = Signal()

        self.sink   = USBRawSuperSpeedStream()
        self.source = USBRawSuperSpeedStream()

        # Temporary?
        self.train_alignment       = Signal()
        self.train_equalizer       = Signal()
        self.rx_polarity           = Signal()

        self.lfps_polling_detected = Signal()
        self.send_lfps_polling     = Signal()
        self.total_lfps_sent       = Signal()

        # Debug output.
        self.alignment_offset        = Signal()
        self.rx_gpio                 = Signal()
        self.lfps_signaling_detected = Signal()


    def elaborate(self, platform):
        m = Module()

        # TODO: handle endianness swapping if requested?

        #
        # Low-Frequency Periodic Signaling generator/receiver.
        #
        m.submodules.lfps = lfps = LFPSTransceiver(
            ss_clk_freq=self._clock_frequency,
            fast_clock_frequency=self._fast_clock_frequency
        )
        m.d.comb += [
            lfps.tx_polling               .eq(self.send_lfps_polling),
            self.lfps_polling_detected    .eq(lfps.rx_polling),
            self.total_lfps_sent          .eq(lfps.tx_count),

            # Pass through our Tx GPIO signals directly to our SerDes.
            self._serdes.use_tx_as_gpio   .eq(lfps.drive_tx_gpio),
            self._serdes.tx_gpio          .eq(lfps.tx_gpio),
            self._serdes.tx_idle          .eq(lfps.tx_idle),

            # Capture the Rx GPIO signal from our SerDes.
            lfps.lfps_signaling_detected  .eq(self._serdes.lfps_signaling_detected),

            # Debug
            self.alignment_offset         .eq(self._serdes.alignment_offset),
            self.lfps_signaling_detected  .eq(lfps.lfps_signaling_detected),
            self.rx_gpio                  .eq(self._serdes.rx_gpio)
        ]

        #
        # Raw SerDes control/translation.
        #

        # TODO: replace these with PIPE signals
        m.d.comb += [
            self.ready                    .eq(self._serdes.ready),

            self._serdes.enable           .eq(1),
            self._serdes.rx_align         .eq(self.train_alignment),
            self._serdes.rx_polarity      .eq(self.rx_polarity),
            self._serdes.train_equalizer  .eq(self.train_equalizer),

            self._serdes.sink             .stream_eq(self.sink,           endian_swap=self._little_endian),
            self.source                   .stream_eq(self._serdes.source, endian_swap=self._little_endian)
        ]


        return m
