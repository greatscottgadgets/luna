#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 physical-layer abstraction."""

from nmigen import *

from ...stream  import USBRawSuperSpeedStream
from .scrambling import Scrambler, Descrambler


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

    def __init__(self, *, phy):
        self._phy = phy

        #
        # I/O port
        #

        # Physical link state.
        self.physical_layer_ready  = Signal()
        self.invert_rx_polarity    = Signal()

        # Scrambling control.
        self.enable_scrambling     = Signal()

        # Raw data streams.
        self.sink                  = USBRawSuperSpeedStream()
        self.source                = USBRawSuperSpeedStream()

        # Temporary?
        self.train_alignment       = Signal()
        self.train_equalizer       = Signal()

        # Receiver detection.
        self.perform_rx_detection  = Signal()
        self.link_partner_detected = Signal()

        # LFPS control.
        self.send_lfps_polling     = Signal()
        self.lfps_polling_detected = Signal()
        self.total_lfps_sent       = Signal(16)



    def elaborate(self, platform):
        m = Module()

        #
        # PHY interfacing.
        #
        m.d.comb += [

            # Indicate that the physical layer is ready as soon as our PHY has started up.
            self.physical_layer_ready    .eq(self._phy.ready),

            # Pass along most of our low-level signals to the PHY.
            # TODO: translate these to PIPE
            self._phy.rx_polarity        .eq(self.invert_rx_polarity),
            self._phy.train_alignment    .eq(self.train_alignment),
            self._phy.send_lfps_polling  .eq(self.send_lfps_polling),
            self._phy.train_equalizer    .eq(self.train_equalizer),
            self.lfps_polling_detected   .eq(self._phy.lfps_polling_detected),

            # For now, pretend we always see a receiver.
            self.link_partner_detected   .eq(1)
        ]


        #
        # Scrambling.
        #
        m.submodules.scrambler = scrambler = Scrambler()
        m.d.comb += [
            scrambler.enable  .eq(self.enable_scrambling),
            scrambler.clear   .eq(~self.enable_scrambling),

            scrambler.sink    .stream_eq(self.sink),
            self._phy.sink    .stream_eq(scrambler.source)
        ]

        #
        # De-scrambling.
        #
        m.submodules.descrambler = descrambler = Descrambler()
        m.d.comb += [
            descrambler.enable  .eq(self.enable_scrambling),

            descrambler.sink    .stream_eq(self._phy.source),
            self.source         .stream_eq(descrambler.source)
        ]

        return m
