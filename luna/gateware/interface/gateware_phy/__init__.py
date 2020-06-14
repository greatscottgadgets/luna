#
# This file is part of LUNA.
#

import logging
from nmigen import Signal, Module, Cat, Elaboratable, ClockSignal


class GatewarePHY(Elaboratable):
    """ Gateware that implements a UTMI-compatible transciever using raw FPGA I/O.

    Clock Domains
    -------------

    usb:
        Our 12 MHz USB clock domain which will match each of the signals below.
        Should be phase-related to the 48MHz clock (e.g. divided down from it) to avoid
        the need for explicit synchronization on clock domain crossings.
    usb_io:
        The core 48MHz clock domain in which USB clock recovery and sampling is performed.
        Must be phase related to our ``usb`` clock domain.

    Attributes
    ----------

    tx_data: Signal(8), input
        data to be transmitted; valid when tx_valid is asserted
    tx_valid: Signal(), input
        asserted when data is to be transmitted; indicates the data_in byte is valid;
        de-asserting this line terminates the transmission
    tx_ready: Signal(), output
        indicates the the PHY is ready to accept a new byte of data, and that the transmitter 
        should move on to the next byte after the given cycle

    rx_data: Signal(8), output
        data received from the PHY; valid when rx_valid is asserted
    rx_valid: Signal(), output
        indicates that the data present on rx_data is new and valid data; goes high for a single usb 
        clock cycle to indicate new data is ready
    rx_active: Signal(), output
        indicates that the PHY is actively receiving data from the host; data is only valid when
        :attr:``rx_valid`` is high
    rx_error: Signal(), output
        indicates that an error has occurred in the current transmission

    rx_complete: Signal(), output:
        strobe that goes high for one cycle when a packet rx is complete


    line_state: Signal(2), output
        Indicates the current state of the D+ and D- lines. Matches the UTMI specification values,
        where 0 = SE0, 1=K, and 2=J.
    vbus_valid: Signal(), output
        Indicates that a valid VBUS signal is present. This signal is valid iff the I/O parameter
        contains a ``vbus_valid`` element; otherwise it is hard connected to '1'
    session_end: Signal(), output
        Indicates that no VBUS signal is present. This signal is valid iff the I/O parameter
        contains a ``vbus_valid`` element; otherwise it is hard connected to '0'

    xcvr_select: Signal(2), input
        Selects the active USB speed. This transceiever only functions as a full speed transciever; so
        this signal is effectively ignored. To support connection to high-speed gateware, this module
        will prevent the USB lines from being driven when this signal is 0b00; allowing the gateware to
        attempt a high-speed detection handshake without adverse affect.
    term_select: Signal(), input
        When asserted, this will connect the device's full speed pull-up resistor.
    op_mode: Signal(2), input
        Selects the operating mode of the UTMI transceiever. A value of 0 causes normal operationg;
        a value of 1 prevents D+ and D- from being driven; and a value of 2 disables bit-stuffing.

    dm_pulldown: Signal(), input
        When asserted, this will indicate that the host-mode's D- pulldown should be connected.
    dm_pulldown: Signal(), input
        When asserted, this will indicate that the host-mode's D+ pulldown should be connected.

    Parameters
    -----------

    io: Record(d_p, d_n, [pullup], [pulldown], [vbus_valid])
        A record containing the raw I/O signals to be used to drive our I/O-based USB connnection.
        The ``d_p`` and ``d_n`` signals are mandaory; the ``pullup``, ``pulldown``,
        and ``vbus_valid`` signals are optional.
    """
        

    def __init__(self, *, io):
        self._io = io
        logging.warn("Using not-yet-functional GatewarePHY! Things will be broken.")

        #
        # I/O port
        #
        self.tx_data     = Signal(8)
        self.tx_valid    = Signal()
        self.tx_ready    = Signal()

        self.rx_data     = Signal(8)
        self.rx_valid    = Signal()
        self.rx_active   = Signal()
        self.rx_error    = Signal()
        self.rx_complete = Signal()

        self.line_state  = Signal(2)
        self.vbus_valid  = Signal()
        self.session_end = Signal()

        self.xcvr_select = Signal(2)
        self.term_select = Signal()
        self.op_mode     = Signal(2)

        self.dp_pulldown = Signal()
        self.dm_pulldown = Signal()


    def elaborate(self, platform):
        m = Module()


        #
        # General state signals.
        #

        # Our line state is always taken directly from D- and D+.
        m.d.comb += self.line_state.eq(Cat(self._io.d_n.i, self._io.d_p.i))

        # If we have a ``vbus_valid`` indication, use it to drive our ``vbus_valid``
        # signal. Otherwise, we'll pretend ``vbus_valid`` is always true, for compatibility.
        if hasattr(self._io, 'vbus_valid'):
            m.d.comb += [
                self.vbus_valid   .eq(self._io.vbus_valid),
                self.session_end  .eq(~self._io.vbus_valid)
            ]
        else:
            m.d.comb += [
                self.vbus_valid   .eq(1),
                self.session_end  .eq(0)
            ]


        #
        # General control signals.
        #

        # If we have a pullup signal, drive it based on ``term_select``.
        if hasattr(self._io, 'pullup'):
            m.d.comb += self._io.pullup.eq(self.term_select)

        # If we have a pulldown signal, drive it based on our pulldown controls.
        if hasattr(self._io, 'pulldown'):
            m.d.comb += self._io.pullup.eq(self.dm_pulldown | self.dp_pulldown)


        return m
