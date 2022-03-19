#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import logging

from amaranth    import *

from ...usb.stream  import USBRawSuperSpeedStream


class SerDesPHY(Elaboratable):
    """ Abstract base class for soft PIPE implementations.

    Currently compliant with the PHY Interface for PCI Express, revision 3.0,
    with the following tweaks:

        - Following Amaranth conventions, reset is active high, rather than active low.

    See Table 5-2 in the PIPE specification r3 for a definition of these signals. Documenting them
    locally is pending; and should be completed once we've settled on a spec version.
    """

    # Default to implementing the 32-bit PIPE standard, but allow subclasses to override this.
    INTERFACE_WIDTH = 32

    # Mappings of interface widths to DataBusWidth parameters.
    _DATA_BUS_WIDTHS = {
        32: 0b00,
        16: 0b01,
        8 : 0b10
    }

    def __init__(self, serdes, ss_clk_frequency, fast_clk_frequency):
        assert ss_clk_frequency   >= 125e6
        assert fast_clk_frequency >= 200e6

        logging.warning("The SerDes-based USB3 PHY is not at all complete.")
        logging.warning("Do not expect -anything- to work!")

        self._serdes               = serdes
        self._clock_frequency      = ss_clk_frequency
        self._fast_clock_frequency = fast_clk_frequency

        # Ensure we have a valid interface width.
        if self.INTERFACE_WIDTH not in self._DATA_BUS_WIDTHS:
            raise ValueError(f"Soft PIPE does not support a data bus width of {self.INTERFACE_WIDTH}!")

        # Compute the width of our data and control signals for this class.
        data_width = self.INTERFACE_WIDTH * 8
        ctrl_width = self.INTERFACE_WIDTH * 1

        #
        # PIPE interface standard.
        #

        # Full-PHY Control and status.
        self.rate             = Signal()
        self.reset            = Signal()
        self.phy_reset        = Signal() # ?
        self.phy_mode         = Signal(2)
        self.phy_status       = Signal()
        self.elas_buf_mode    = Signal()
        self.power_down       = Signal(2)
        self.power_present    = Signal(reset=1)
        self.data_bus_width   = Const(self._DATA_BUS_WIDTHS[self.INTERFACE_WIDTH], 2)

        # Transmit bus.
        self.tx_clk           = Signal()
        self.tx_data          = Signal(data_width)
        self.tx_datak         = Signal(ctrl_width)

        # Transmit configuration & status.
        self.tx_compliance    = Signal()    # not supported
        self.tx_oneszeroes    = Signal()    # not supported
        self.tx_deemph        = Signal(2)   # not supported
        self.tx_margin        = Signal(3)   # not supported
        self.tx_swing         = Signal()    # not supported
        self.tx_detrx_lpbk    = Signal()
        self.tx_elecidle      = Signal()

        # Receive bus.
        self.pclk             = Signal()
        self.rx_data          = Signal(data_width)
        self.rx_datak         = Signal(ctrl_width)
        self.rx_valid         = Signal()    # not supported

        # Receiver configuration & status.
        self.rx_status        = Array((Signal(3), Signal(3)))
        self.rx_polarity      = Signal()
        self.rx_elecidle      = Signal()
        self.rx_termination   = Signal()
        self.rx_eq_training   = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Reset and status.
        #
        m.d.comb += [
            self._serdes.reset                .eq(self.reset),
            self.phy_status                   .eq(~self._serdes.ready)
        ]


        #
        # Transmit path.
        #
        m.d.comb += [
            self._serdes.sink.data            .eq(self.tx_data),
            self._serdes.sink.ctrl            .eq(self.tx_datak),
            self._serdes.sink.valid           .eq(1),
            self._serdes.tx_idle              .eq(self.tx_elecidle),
        ]


        #
        # Receive path.
        #
        m.d.comb += [
            self.rx_data                      .eq(self._serdes.source.data),
            self.rx_datak                     .eq(self._serdes.source.ctrl),
            self.rx_valid                     .eq(self._serdes.source.valid),
            self._serdes.rx_termination       .eq(self.rx_termination),
            self._serdes.rx_polarity          .eq(self.rx_polarity),
            self._serdes.rx_eq_training       .eq(self.rx_eq_training),
        ]


        #
        # LFPS generation/detection.
        #
        m.d.comb += [
            self._serdes.send_lfps_signaling  .eq(self.tx_detrx_lpbk & self.tx_elecidle),
            self.rx_elecidle                  .eq(~self._serdes.lfps_signaling_received),
        ]


        return m
