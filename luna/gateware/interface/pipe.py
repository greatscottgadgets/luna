# nmigen: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 PIPE interfacing gateware. """

from nmigen                     import *
from nmigen.lib.fifo            import AsyncFIFOBuffered
from nmigen.hdl.ast             import Past

from luna                       import top_level_cli
from luna.gateware.platform     import NullPin

from ..usb.stream               import USBRawSuperSpeedStream
from ..usb.usb3.physical.coding import COM




class GearedPIPEInterface(Elaboratable):
    """ Module that presents a post-gearing PIPE interface, performing gearing in I/O hardware.

    This module presents a public interface that's identical to a standard PIPE PHY,
    with the following exceptions:

        - ``tx_data``    is 32 bits wide, rather than 16
        - ``tx_datak``   is 4  bits wide, rather than  2
        - ``rx_data``    is 32 bits wide, rather than 16
        - ``rx_datak``   is 4  bits wide, rather than  2
        - ``phy_status`` is 2 bits wide, rather than 1
        - ``rx_status``  is now an array of two 3-bit signals

    This module *requires* that a half-rate / 125MHz clock that's in phase with the ``pipe_io``
    clock be provided to the ``pipe`` domain. This currently must be handled per-device, so it
    is the responsibility of the platform's clock domain generator.

    This module optionally can connect the PIPE I/O clock (``pclk``) to the design's clocking
    network. This configuration is recommended.


    Parameters
    ----------
    pipe: PIPE I/O resource
        The raw PIPE interface to be worked with.
    handle_clocking: boolean, optional
        If true or not provided, this module will attempt to handle some clock connections
        for you. This means that ClockSignal("pipe_io") will be automatically driven by the
        PHY's clock (``pclk``), and ``tx_clk`` will automatically be tied to ClockSignal("pipe").
    """

    # Provide standard XDR settings that can be used when requesting an interface.
    GEARING_XDR = {
        'tx_data': 2, 'tx_datak': 2, 'tx_clk':   2,
        'rx_data': 2, 'rx_datak': 2, 'rx_valid': 2,
        'phy_status': 2, 'rx_status': 2
    }


    def __init__(self, *, pipe, invert_rx_polarity_signal=False):
        self._io = pipe
        self._invert_rx_polarity_signal = invert_rx_polarity_signal

        #
        # I/O port
        #

        self.tx_clk      = Signal()
        self.tx_data     = Signal(32)
        self.tx_datak    = Signal(4)

        self.pclk        = Signal()
        self.rx_data     = Signal(32)
        self.rx_datak    = Signal(4)
        self.rx_valid    = Signal()

        self.phy_status  = Signal(2)
        self.rx_status   = Array((Signal(3), Signal(3)))

        self.rx_polarity = Signal()

        # Copy each of the elements from our core PIPE PHY, so we act mostly as a passthrough.
        for name, *_ in self._io.layout:

            # If we're handling the relevant signal manually, skip it.
            if hasattr(self, name):
                continue

            # Grab the raw I/O...
            io = getattr(self._io, name)

            # If it's a tri-state, copy it as-is.
            if hasattr(io, 'oe'):
                setattr(self, name, io)

            # Otherwise, copy either its input...
            elif hasattr(io,  'i'):
                setattr(self, name, io.i)

            # ... or its output.
            elif hasattr(io,  'o'):
                setattr(self, name, io.o)

            else:
                raise ValueError(f"Unexpected signal {name} with subordinates {io} in PIPE PHY!")


    def elaborate(self, platform):
        m = Module()


        m.d.comb += [
            # Drive our I/O boundary clock with our PHY clock directly,
            # and replace our geared clock with the relevant divided clock.
            ClockSignal("ss_io")     .eq(self._io.pclk.i),
            self.pclk                .eq(ClockSignal("ss")),

            # Drive our transmit clock with an DDR output driven from our full-rate clock.
            # Re-creating the clock in this I/O cell ensures that our clock output is phase-aligned
            # with the signals we create below. [UG471: pg128, "Clock Forwarding"]
            self._io.tx_clk.o_clk    .eq(ClockSignal("ss_io")),
            self._io.tx_clk.o0       .eq(1),
            self._io.tx_clk.o1       .eq(0),
        ]

        # Set up our geared I/O clocks.
        m.d.comb += [
            # Drive our transmit signals from our transmit-domain clocks...
            self._io.tx_data.o_clk     .eq(ClockSignal("ss")),
            self._io.tx_datak.o_clk    .eq(ClockSignal("ss")),

            # ... and drive our receive signals from our primary/receive domain clock.
            self._io.rx_data.i_clk     .eq(ClockSignal("ss_shifted")),
            self._io.rx_datak.i_clk    .eq(ClockSignal("ss_shifted")),
            self._io.rx_valid.i_clk    .eq(ClockSignal("ss_shifted")),
            self._io.phy_status.i_clk  .eq(ClockSignal("ss_shifted")),
            self._io.rx_status.i_clk   .eq(ClockSignal("ss_shifted")),
        ]

        #
        # Output handling.
        #
        m.d.ss += [
            # We'll output tx_data bytes {0, 1} and _then_ {2, 3}.
            self._io.tx_data.o0   .eq(self.tx_data [ 0:16]),
            self._io.tx_data.o1   .eq(self.tx_data [16:32]),
            self._io.tx_datak.o0  .eq(self.tx_datak[ 0: 2]),
            self._io.tx_datak.o1  .eq(self.tx_datak[ 2: 4])
        ]

        #
        # Input handling.
        #
        m.d.ss += [
            # We'll capture rx_data bytes {0, 1} and _then_ {2, 3}.
            self.rx_data [ 0:16]  .eq(self._io.rx_data.i0),
            self.rx_data [16:32]  .eq(self._io.rx_data.i1),
            self.rx_datak[ 0: 2]  .eq(self._io.rx_datak.i0),
            self.rx_datak[ 2: 4]  .eq(self._io.rx_datak.i1),

            # Split our RX_STATUS to march our other geared I/O.
            self.phy_status[0]    .eq(self._io.phy_status.i0),
            self.phy_status[1]    .eq(self._io.phy_status.i1),

            self.rx_status[0]     .eq(self._io.rx_status.i0),
            self.rx_status[1]     .eq(self._io.rx_status.i1),


            # RX_VALID indicates that we have symbol lock; and thus should remain
            # high throughout our whole stream. Accordingly, we can squish both values
            # down into a single value without losing anything, as it should remain high
            # once our signal has been trained.
            self.rx_valid         .eq(self._io.rx_valid.i0 & self._io.rx_valid.i1),
        ]



        # Allow us to invert the polarity of our ``rx_polarity`` signal, to account for
        # boards that have their Rx+/- lines swapped.
        if self._invert_rx_polarity_signal:
            m.d.comb += self._io.rx_polarity.eq(~self.rx_polarity)
        else:
            m.d.comb += self._io.rx_polarity.eq(self.rx_polarity)

        return m


