# nmigen: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 PIPE interfacing gateware. """

from nmigen import *

from luna                   import top_level_cli
from luna.gateware.platform import NullPin

class GearedPIPEInterface(Elaboratable):
    """ Module that presents a post-gearing PIPE interface.

    This module presents a public interface that's identical to a standard PIPE PHY,
    with the following exceptions:

        - ``tx_data``   is 32 bits wide, rather than 16
        - ``tx_data_k`` is 4  bits wide, rather than  2
        - ``rx_data``   is 32 bits wide, rather than 16
        - ``rx_data_k`` is 4  bits wide, rather than  2

    This module *requires* that a half-rate / 125MHz clock that's in phase with the ``pipe_io``
    clock be provided to the ``pipe`` domain. This currently must be handled per-device, so it
    is the responsibility of the platform's clock domain generator.

    This module optionally can connect the PIPE I/O clock (``pclk``) to the design's clocking
    network. This configuration is recommended.

    Attributes
    ----------
    rx_bytes: Array of four Signal(8)s, output
        Alias for rx_data broken into four discrete bytes.
    tx_bytes: Array of four Signal(8)s, input
        Alias for tx_data broken into four discrete bytes.


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
        'tx_data': 2, 'tx_data_k': 2,
        'rx_data': 2, 'rx_data_k': 2,
    }


    def __init__(self, *, pipe, handle_clocking=True):
        self._io = pipe
        self._handle_clocking = handle_clocking

        #
        # I/O port
        #

        # Copy each of the elements from our core PIPE PHY, so we act mostly as a passthrough.
        for name, *_ in self._io.layout:
            setattr(self, name, getattr(self._io, name))

        # Create shortcuts for defining I/O pin equivalent records.
        # This allows us to present a consistent interface with the original I/O.
        out_record     = lambda size : Record([('o', size)])
        in_record      = lambda size : Record([('i', size)])

        # Override the I/O we'll handle specially.
        self.tx_clk    = out_record(1)
        self.tx_data   = out_record(32)
        self.tx_data_k = out_record(4)

        self.pclk      = in_record(1)
        self.rx_data   = in_record(32)
        self.rx_data_k = in_record(4)

        # Create ``tx_bytes`` and ``rx_bytes`` aliases with easy byte access.
        self.tx_bytes = Array(self.tx_data.o[i:i+8] for i in range(0, 32, 8))
        self.rx_bytes = Array(self.rx_data.i[i:i+8] for i in range(0, 32, 8))

    def elaborate(self, platform):
        m = Module()

        # If we're handling clocking, automatically tie pclk/tx_clk to the appropriate domains.
        if self._handle_clocking:
            m.d.comb += [
                # Drive our I/O boundary clock with our PHY clock directly,
                # and replace our geared clock with the relevant divided clock.
                ClockSignal("pipe_io_rx")  .eq(self._io.pclk.i),
                self.pclk.i                .eq(ClockSignal("pipe_rx")),

                # Drive our raw TX clock with our I/O clock, and drive our local copy
                # with our geared-down clock.
                self._io.tx_clk.o          .eq(ClockSignal("pipe_io_tx")),
                self.tx_clk.o              .eq(ClockSignal("pipe_tx"))
            ]

        # DDR I/O setup: we'll tie our geared I/O clocks to our raw PHY clock.
        # Our PHY is half-rate, but
        m.d.comb += [
            self._io.tx_data.o_clk    .eq(ClockSignal("pipe_tx")),
            self._io.tx_data_k.o_clk  .eq(ClockSignal("pipe_tx")),

            self._io.rx_data.i_clk    .eq(ClockSignal("pipe_rx")),
            self._io.rx_data_k.i_clk  .eq(ClockSignal("pipe_rx")),
        ]

        # Handle our geared inputs.
        m.d.comb += [
            # We'll output tx_data bytes {0, 1} and _then_ {2, 3}.
            self._io.tx_data.o0       .eq(self.tx_data.o[0:16]),
            self._io.tx_data.o1       .eq(self.tx_data.o[16:32]),
            self._io.tx_data_k.o0     .eq(self.tx_data_k.o[0:2]),
            self._io.tx_data_k.o1     .eq(self.tx_data_k.o[2:4]),

            # We'll capture rx_data bytes {0, 1} and _then_ {2, 3}.
            self.rx_data.i[0:16]      .eq(self._io.rx_data.i0),
            self.rx_data.i[16:32]     .eq(self._io.rx_data.i1),
            self.rx_data_k.i[0:2]     .eq(self._io.rx_data_k.i0),
            self.rx_data_k.i[2:4]     .eq(self._io.rx_data_k.i1),
        ]

        return m
