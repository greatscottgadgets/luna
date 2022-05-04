# amaranth: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" USB3 PIPE interfacing gateware. """

from amaranth import *
from amaranth.lib.cdc  import FFSynchronizer, ResetSynchronizer
from amaranth.lib.fifo import AsyncFIFOBuffered


class PIPEInterface(Elaboratable):
    """ Interface present on hardware that implements the PHY Interface for PCI Express and USB 3.0 (PIPE).

    This interface is compliant with the PHY Interface For the PCI Express and USB 3.0
    Architectures, Version 3.0 specification. Unless otherwise noted, the descriptions of
    the signals as stated in this specification take precedence over the ones provided here.

    The directions of the signals are given from the PHY perspective, i.e. a signal described as
    an "output" is driven by the PHY and received by the MAC.

    Parameters
    ----------
    width : int
        Interface width, in symbols.

    Ports
    -----
    reset : Signal(), input
        Active-high, asynchronous reset for the PHY receiver and transmitter.
    clk : Signal(), input
        Reference clock for the PHY receiver and transmitter. The specifications for this clock
        (frequency, jitter, phase relationship to other clocks) are PHY implementation dependent
        and must be specified by the implementation.
    pclk : Signal(), output
        Clock for the PHY interface. Unless otherwise specified, all other signals are synchronous
        to the rising edge of this clock. This clock is derived from the reference clock; if
        the reference clock is spread spectrum modulated, so will be the interface clock.
        The frequency of this clock depends on the ``phy_mode`` and ``rate`` inputs. Note that
        the supported combinations of ``phy_mode`` and ``rate`` are PHY implementation dependent.

    tx_data : Signal(width * 8), input
    tx_datak : Signal(width), input
        Transmit data bus. Bits [7:0] are the first symbol to be transmitted, bits [15:8] (if any)
        are the second symbol, and so on.
    rx_data : Signal(width * 8), output
    rx_datak : Signal(width), output
        Receive data bus. Bits [7:0] are the first symbol that has been received, bits [15:8]
        (if any) are the second symbol, and so on.

    phy_mode : Signal(2), input
        PHY operating mode; 0 for PCI Express, 1 for SuperSpeed USB. The allowed values for this
        input are PHY implementation dependent. The PHY must be reset after changing this input.
    elas_buf_mode : Signal(1), input
        Elastic buffer operating mode; 0 for Nominal Half-full, 1 for Nominal Empty. The allowed
        values for this input are PHY implementation dependent. The PHY must be reset after
        changing this input.
    rate : Signal(1), input
        Link signaling rate; 0 for 2.5 GT/s, 1 for 5 GT/s. The allowed values for this input are
        PHY implementation dependent. Whether changing this signal affects the ``pclk`` frequency
        or the effective data bus width is PHY implementation dependent. The change of this input
        is acknowledged by a single-cycle assertion of ``phy_status``.
    power_down : Signal(2), input
        Protocol-specific power management mode, as per the PIPE specification. This signal is
        synchronous to ``pclk`` if the clock is running, and asynchronous otherwise. The change
        of this input is acknowledged by a single-cycle assertion of ``phy_status`` if ``pclk``
        is running, or by deassertion of ``phy_status`` otherwise.
    tx_deemph : Signal(2), input
        Transmitter de-emphasis level; 0 for -6 dB, 1 for -3.5 dB, 2 for 0 dB. The allowed values
        for this input are PHY implementation dependent.
    tx_margin : Signal(3), input
        Transmitter voltage levels, as per the PIPE specification. The allowed values for this
        input and their meanings are PHY implementation dependent.
    tx_swing : Signal(1)
        Transmitter voltage swing level. The allowed values for this input and their meanings
        are PHY implementation dependent.
    tx_detrx_lpbk : Signal(), input
    tx_elec_idle : Signal(), input
        Protocol-specific transmit control signals, as per the PIPE specification. Depending on
        the state of ``phy_mode`` and ``power_down`` inputs, these inputs direct the PHY
        transmitter to transmit data from the transmit data bus, loop back received data, go into
        Electrical Idle, transmit beacon or LFPS signaling, or perform a receiver detection
        operation. These signals are synchronous to ``pclk`` if the clock is running, and
        asynchronous otherwise. The completion of a receiver detection operation is acknowledged
        by a single-cycle assertion of ``phy_status`` if ``pclk`` is running, or by asserting
        ``phy_status`` until the MAC deasserts ``tx_detrx_lpbk`` otherwise.
    tx_compliance : Signal(), input
        If asserted, sets the running disparity to negative for the first symbol on the transmit
        data bus. This signal is implemented only for PHYs that can operate in the PCI Express mode.
    tx_ones_zeroes : Signal(), input
        If asserted, the PHY transmits an alternating sequence of 50-250 ones and 50-250 zeroes
        instead of the data on the transmit data bus. This signal is implemented only for PHYs
        that can operate in the SuperSpeed USB mode.
    rx_polarity : Signal(), input
        If asserted, the PHY receiver inverts the received serial data.
    rx_eq_training : Signal(), input
        If asserted, the PHY receiver bypasses normal operation to perform equalization training.
        Whether this signal is implemented is PHY implementation dependent.
    rx_termination : Signal(), input
        If asserted, the PHY receiver presents receiver terminations. Whether this signal is
        implemented is PHY implementation dependent.

    phy_status : Signal(), output
        PHY operation completion status, as per the PIPE specification. This signal is synchronous
        to ``pclk`` if the clock is running, and asynchronous otherwise.
    rx_valid : Signal(), output
        If asserted, the PHY receiver has symbol lock and there is valid data on the data bus.
    rx_status : Signal(3), output
        Indicates one of the four possible receiver errors (8b10b decode error, disparity error,
        elastic buffer overflow or underflow), the addition or removal of symbols as a part of
        elastic buffer management, or the completion of a receiver detection operation. This signal
        is synchronous to ``pclk`` if the clock is running, and asynchronous otherwise.
    rx_elec_idle : Signal(), output
        If asserted, depending on the state of ``phy_mode`` and ``power_down`` inputs, indicates
        detection of Electrical Idle, beacon signaling, or LFPS signaling. This signal is
        asynchronous.
    power_present : Signal(), output
        If asserted, voltage is present on Vbus. Whether this signal is implemented is PHY
        implementation dependent.
    """

    # Mappings of interface widths to DataBusWidth parameters.
    _DATA_BUS_WIDTHS = {
        4: 0b00,
        2: 0b01,
        1: 0b10
    }

    def __init__(self, *, width):
        # Ensure we have a valid interface width.
        if width not in (1, 2, 4):
            raise ValueError(f"PIPE does not support a data bus width of {width}")
        self.width          = width

        #
        # Clock and reset signals.
        #
        self.reset          = Signal()
        self.clk            = Signal()
        self.pclk           = Signal()

        #
        # Transmit and receive data buses.
        #
        self.tx_data        = Signal(self.width * 8)
        self.tx_datak       = Signal(self.width * 1)
        self.rx_data        = Signal(self.width * 8)
        self.rx_datak       = Signal(self.width * 1)

        #
        # Control signals.
        #
        self.phy_mode       = Signal(2)
        self.elas_buf_mode  = Signal(1)
        self.rate           = Signal(1)
        self.power_down     = Signal(2)
        self.tx_deemph      = Signal(2)
        self.tx_margin      = Signal(3)
        self.tx_swing       = Signal(1)
        self.tx_detrx_lpbk  = Signal()
        self.tx_elec_idle   = Signal()
        self.tx_compliance  = Signal()
        self.tx_ones_zeroes = Signal()
        self.rx_polarity    = Signal()
        self.rx_eq_training = Signal()
        self.rx_termination = Signal()

        #
        # Status signals.
        #
        self.data_bus_width = Const(self._DATA_BUS_WIDTHS[self.width], 2)
        self.phy_status     = Signal()
        self.rx_valid       = Signal()
        self.rx_status      = Signal(3)
        self.rx_elec_idle   = Signal()
        self.power_present  = Signal()



class AsyncPIPEInterface(PIPEInterface, Elaboratable):
    """ Gateware that transfers PIPE interface signals between clock domains.

    The PIPE specification defines the PHY interface signals to be synchronous to a PHY-generated
    clock ``pclk``, and asynchronous if ``pclk`` is not running. The MAC will typically not be
    clocked by ``pclk`` for the following non-exhaustive list of reasons:
        * The MAC implements P2 (for PCI Express) or P3 (for SuperSpeed USB) power states where
          the PHY-generated clock is not running;
        * The PHY-generated clock is faster than the maximum frequency at which the MAC can run;
        * The MAC implements rate switching (for PCI Express), and needs to support PHYs that
          change the PHY-generated clock frequency depending on the rate;
        * The PHY is required to use a spread spectrum clock in the SuperSpeed USB mode, and
          this would interfere with the MAC operation;
        * etc.

    This gateware transfers the PIPE interface signals between the PHY and MAC clock domains,
    optionally performing gearing to adapt the PHY data bus width and interface clock rate to
    the MAC capabilities. With the exception of ``reset``, ``clk`` and ``pclk``, all of the signals
    in this gateware are synchronous to the specified Amaranth clock domain, ``ss`` by default.
    The ``pclk`` signal is driven by the clock of this domain.

    This gateware does not currently support asynchronous signaling in the deepest PHY power state.
    """

    def __init__(self, phy, *, width, domain="ss"):
        if width < phy.width:
            raise ValueError(f"Async PIPE interface cannot adapt PHY data bus width {phy.width} "
                             f"to MAC data bus width {width}")
        super().__init__(width=width)
        self.phy            = phy
        self._domain        = domain


    def elaborate(self, platform):
        m = Module()

        phy     = self.phy
        ratio   = self.width // phy.width

        #
        # Clocking and resets.
        #
        m.domains.phy = ClockDomain(local=True, async_reset=True)
        m.d.comb += [
            phy.clk             .eq(self.clk),
            ClockSignal("phy")  .eq(phy.pclk),
        ]

        m.submodules += ResetSynchronizer(phy.reset, domain="phy")
        m.d.comb += [
            phy.reset           .eq(self.reset),
        ]


        #
        # Common gearbox signals.
        #
        if ratio == 1:
            gear_index   = Const(0)
            gear_advance = Const(1)
        else:
            gear_index   = Signal(range(ratio))
            gear_advance = Signal()
            m.d.phy  += gear_index   .eq(gear_index + 1)
            m.d.comb += gear_advance .eq(gear_index == ratio - 1)


        #
        # Transmit data bus and related control signals.
        #
        geared_tx_data          = Signal.like(self.tx_data)
        geared_tx_datak         = Signal.like(self.tx_datak)
        geared_tx_compliance    = Signal.like(self.tx_compliance)
        geared_tx_ones_zeroes   = Signal.like(self.tx_ones_zeroes)
        mac_tx_bus_signals = Cat(
            self.tx_data,
            self.tx_datak,
            # These control signals are additional inputs to the 8b10b encoder; and must be
            # exactly synchronized to the transmit data bus.
            self.tx_compliance,
            self.tx_ones_zeroes,
        )
        phy_tx_bus_signals = Cat(
            geared_tx_data,
            geared_tx_datak,
            geared_tx_compliance,
            geared_tx_ones_zeroes,
        )

        m.d.comb += [
            phy.tx_data         .eq(geared_tx_data .word_select(gear_index, len(phy.tx_data))),
            phy.tx_datak        .eq(geared_tx_datak.word_select(gear_index, len(phy.tx_datak)))
        ]
        # TxCompliance affects only the first transmitted symbol; keep that property after gearing.
        with m.If(gear_index == 0):
            m.d.comb += phy.tx_compliance   .eq(geared_tx_compliance)
        # TxOnesZeroes replaces all symbols on the transmit data bus.
        m.d.comb += phy.tx_ones_zeroes  .eq(geared_tx_ones_zeroes)

        m.submodules.tx_fifo = tx_fifo = AsyncFIFOBuffered(
            width=len(mac_tx_bus_signals),
            depth=4,
            w_domain="sync",
            r_domain="phy"
        )
        m.d.comb += [
            tx_fifo.w_data      .eq(mac_tx_bus_signals),
            tx_fifo.w_en        .eq(1),
            phy_tx_bus_signals  .eq(tx_fifo.r_data),
            tx_fifo.r_en        .eq(gear_advance)
        ]


        #
        # Receive data bus and related control signals.
        #
        geared_rx_data          = [Signal.like(phy.rx_data,     name_suffix=f"_{i}") for i in range(ratio)]
        geared_rx_datak         = [Signal.like(phy.rx_datak,    name_suffix=f"_{i}") for i in range(ratio)]
        geared_rx_valid         = [Signal.like(phy.rx_valid,    name_suffix=f"_{i}") for i in range(ratio)]
        geared_rx_status        = [Signal.like(phy.rx_status,   name_suffix=f"_{i}") for i in range(ratio)]
        geared_phy_status       = [Signal.like(phy.phy_status,  name_suffix=f"_{i}") for i in range(ratio)]
        phy_rx_bus_signals = Cat(
            phy.rx_data,
            phy.rx_datak,
            phy.rx_valid,
            phy.rx_status,
            phy.phy_status,
        )
        mac_rx_bus_signals = Cat((
            geared_rx_data[i],
            geared_rx_datak[i],
            # These control signals are additional outputs from the 8b10b decoder, comma aligner,
            # and elastic buffer; and must be exactly synchronized to the receive data bus.
            geared_rx_valid[i],
            geared_rx_status[i],
            # The PhyStatus signal will be asserted on the same cycle as RxStatus; and must be
            # exactly synchronized with it (and so the data bus, even though it has no direct
            # relationship with the latter).
            geared_phy_status[i],
        ) for i in range(ratio))

        m.d.comb += [
            self.rx_data        .eq(Cat(geared_rx_data)),
            self.rx_datak       .eq(Cat(geared_rx_datak))
        ]
        # RxValid is asserted if all of the symbols are valid.
        with m.If(Cat(geared_rx_valid).any()):
            m.d.comb += self.rx_valid       .eq(1)
        # Several different conditions can be indicated for different symbols transferred over
        # RxData/RxDataK; when this happens, the condition with the highest priority is indicated.
        # The complete priority order (lowest to highest) is:
        #   8. (Received data OK)
        #   7. Receiver detected
        #   6. SKP symbols removed
        #   5. SKP symbols added
        #   4. Disparity errors
        #   3. Elastic buffer underflow
        #   2. Elastic buffer overflow
        #   1. 8B/10B decode error
        for rx_status_code in 0b011, 0b010, 0b001, 0b111, 0b110, 0b101, 0b100:
            with m.If(Cat(geared_rx_status[i] == rx_status_code for i in range(ratio)).any()):
                m.d.comb += self.rx_status      .eq(rx_status_code)
        # PhyStatus is asserted for one cycle once the PHY completes a request submitted by
        # the MAC (and so will never be asserted for two adjacent cycles); or asserted continuously
        # during certain power state transitions (in which case it is unimportant for which exact
        # symbols it is asserted).
        with m.If(Cat(geared_phy_status).any()):
            m.d.comb += self.phy_status     .eq(1)

        m.submodules.rx_fifo = rx_fifo = AsyncFIFOBuffered(
            width=len(mac_rx_bus_signals),
            depth=4,
            w_domain="phy",
            r_domain="sync"
        )
        m.d.phy  += [
            rx_fifo.w_data.word_select(gear_index, len(phy_rx_bus_signals))
                                .eq(phy_rx_bus_signals),
            rx_fifo.w_en        .eq(gear_advance),
        ]
        m.d.comb += [
            mac_rx_bus_signals  .eq(rx_fifo.r_data),
            rx_fifo.r_en        .eq(1)
        ]


        #
        # Control and status signals not related to the data bus.
        #
        m.submodules += [
            # These control and status signals may change while the PHY is active; but they
            # do not need to be precisely synchronized to the data bus, since no specific
            # latency is defined for these signals.
            FFSynchronizer(self.phy_mode,       phy.phy_mode,       o_domain="phy"),
            FFSynchronizer(self.elas_buf_mode,  phy.elas_buf_mode,  o_domain="phy"),
            FFSynchronizer(self.rate,           phy.rate,           o_domain="phy"),
            FFSynchronizer(self.power_down,     phy.power_down,     o_domain="phy"),
            FFSynchronizer(self.tx_deemph,      phy.tx_deemph,      o_domain="phy"),
            FFSynchronizer(self.tx_margin,      phy.tx_margin,      o_domain="phy"),
            FFSynchronizer(self.tx_swing,       phy.tx_swing,       o_domain="phy"),
            FFSynchronizer(self.tx_detrx_lpbk,  phy.tx_detrx_lpbk,  o_domain="phy"),
            FFSynchronizer(self.tx_elec_idle,   phy.tx_elec_idle,   o_domain="phy"),
            FFSynchronizer(self.rx_polarity,    phy.rx_polarity,    o_domain="phy"),
            FFSynchronizer(self.rx_eq_training, phy.rx_eq_training, o_domain="phy"),
            FFSynchronizer(self.rx_termination, phy.rx_termination, o_domain="phy"),
            FFSynchronizer(phy.rx_elec_idle,    self.rx_elec_idle,  o_domain="sync"),
            FFSynchronizer(phy.power_present,   self.power_present, o_domain="sync"),
        ]


        # Rename the default domain to the MAC domain that was requested.
        return DomainRenamer({"sync": self._domain})(m)



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
            self._io.tx_clk.o_clk    .eq(ClockSignal("ss_io_shifted")),
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


