# SPDX-License-Identifier: BSD-3-Clause
""" Common building blocks for Xilinx 7-series targets. """

from math import ceil
from amaranth import *

from .lfps import _LFPS_PERIOD_MAX


class DRPInterface:
    """ Dynamic Reconfiguration Port interface for Xilinx FPGAs. """

    def __init__(self):
        self.lock = Signal(1,   name="drp_lock")
        self.addr = Signal(9,   name="drp_addr")
        self.di   = Signal(16,  name="drp_di")
        self.do   = Signal(16,  name="drp_do")
        self.we   = Signal(1,   name="drp_we")
        self.en   = Signal(1,   name="drp_en")
        self.rdy  = Signal(1,   name="drp_rdy")


class _DRPInterfaceBuffer(Elaboratable):
    """ Gateware that latches DRP transaction inputs, for an arbiter to complete it later. """
    def __init__(self, interface):
        self.intf = interface

        self.addr_latch = Signal.like(interface.addr)
        self.di_latch = Signal.like(interface.di)
        self.we_latch = Signal.like(interface.we)
        self.en_latch = Signal.like(interface.en)


    def elaborate(self, platform):
        m = Module()

        with m.If(self.intf.en):
            m.d.ss += [
                self.addr_latch.eq(self.intf.addr),
                self.di_latch.eq(self.intf.di),
                self.we_latch.eq(self.intf.we),
                self.en_latch.eq(1),
            ]

        with m.Elif(self.intf.rdy):
            m.d.ss += [
                self.en_latch.eq(0),
            ]

        return m


class DRPArbiter(Elaboratable):
    """ Gateware that merges a collection of DRPInterfaces into a single interface.

    To support safe read-modify-write operations, the ``lock`` signal can be used to gain
    exclusive access to the reconfiguration port. After starting a DRP operation with ``lock``
    asserted, and until it is deasserted, no other client will be able to access the port.
    """

    def __init__(self):
        self.shared = DRPInterface()
        self.interfaces = []

    def add_interface(self, interface: DRPInterface):
        self.interfaces.append(interface)


    def elaborate(self, platform):
        m = Module()

        buffers = Array(_DRPInterfaceBuffer(intf) for intf in self.interfaces)
        m.submodules += buffers

        current_idx = Signal(range(len(buffers)))
        current_buf = buffers[current_idx]

        with m.FSM(domain="ss"):

            with m.State("IDLE"):
                for idx in range(len(buffers)):
                    with m.If(buffers[idx].en_latch):
                        m.d.ss += current_idx.eq(idx)
                        m.next = "REQUEST"

            with m.State("REQUEST"):
                m.d.comb += [
                    self.shared.lock.eq(current_buf.intf.lock),
                    self.shared.addr.eq(current_buf.addr_latch),
                    self.shared.di.eq(current_buf.di_latch),
                    self.shared.we.eq(current_buf.we_latch),
                    self.shared.en.eq(current_buf.en_latch),
                ]
                with m.If(self.shared.en):
                    m.next = "REPLY"
                with m.Elif(~current_buf.intf.lock):
                    m.next = "IDLE"

            with m.State("REPLY"):
                m.d.comb += [
                    current_buf.intf.do.eq(self.shared.do),
                    current_buf.intf.rdy.eq(self.shared.rdy),
                ]
                with m.If(self.shared.rdy):
                    with m.If(current_buf.intf.lock):
                        m.next = "REQUEST"
                    with m.Else():
                        m.next = "IDLE"

        return m


class DRPFieldController(Elaboratable):
    """ Gateware that atomically updates part of a word via DRP. """

    def __init__(self, *, addr: int, bits: slice, reset=0):
        self._addr = addr
        self._bits = bits

        self.drp = DRPInterface()

        self.value = Signal(bits.stop - bits.start, reset=reset)


    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.drp.lock.eq(1),
            self.drp.addr.eq(self._addr)
        ]

        current_val = Signal.like(self.drp.do)

        with m.FSM(domain="ss"):
            with m.State("READ"):
                m.d.comb += [
                    self.drp.en.eq(1)
                ]
                m.next = "READ-WAIT"

            with m.State("READ-WAIT"):
                with m.If(self.drp.rdy):
                    m.d.ss += [
                        current_val.eq(self.drp.do),
                        current_val[self._bits].eq(self.value)
                    ]
                    m.next = "WRITE"

            with m.State("WRITE"):
                m.d.comb += [
                    self.drp.di.eq(current_val),
                    self.drp.we.eq(1),
                    self.drp.en.eq(1),
                ]
                m.next = "WRITE-WAIT"

            with m.State("WRITE-WAIT"):
                with m.If(self.drp.rdy):
                    m.next = "IDLE"

            with m.State("IDLE"):
                m.d.comb += self.drp.lock.eq(0)
                with m.If(current_val[self._bits] != self.value):
                    m.next = "READ"

        return m


class GTResetDeferrer(Elaboratable):
    """ Gateware that ensures the mandatory post-configuration period before reset, per Xilinx AR43482. """

    def __init__(self, ss_clock_frequency):
        self._ss_clock_frequency = ss_clock_frequency

        # Reset inputs.
        self.tx_i = Signal()
        self.rx_i = Signal()

        # Reset outputs.
        self.tx_o = Signal()
        self.rx_o = Signal()

        # Status output.
        self.done = Signal()


    def elaborate(self, platform):
        m = Module()

        # Defer reset by 500ns recommended in [AR43482], plus 5% margin.
        cycles = int(self._ss_clock_frequency * 500e-9 * 1.05)
        timer  = Signal(range(cycles))

        # Defer reset immediately after configuration; and never again, even if our domain is reset.
        defer  = Signal(reset=1, reset_less=True)

        with m.If(defer):
            m.d.ss += timer.eq(timer + 1)

            with m.If(timer + 1 == cycles):
                m.d.ss += defer.eq(0)

        with m.Else():
            m.d.comb += [
                self.done.eq(1),
                self.tx_o.eq(self.tx_i),
                self.rx_o.eq(self.rx_i),
            ]

        return m


class GTPRXPMAResetWorkaround(Elaboratable):
    """ Gateware that ensures the required conditions for GTP receiver are met, per UG482. """

    def __init__(self, ss_clock_frequency):
        self._ss_clock_frequency = ss_clock_frequency

        self.i = Signal()
        self.o = Signal()

        self.rxpmaresetdone = Signal()
        self.drp = DRPInterface()


    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.drp.lock.eq(1),
            self.drp.addr.eq(0x011)
        ]

        saved_val = Signal.like(self.drp.do)

        with m.FSM(domain="ss"):
            with m.State("IDLE"):
                m.d.comb += [
                    self.drp.lock.eq(0),
                ]
                with m.If(self.i):
                    m.next = "READ"

            with m.State("READ"):
                m.d.comb += [
                    self.o.eq(1),
                    self.drp.en.eq(1)
                ]
                m.next = "READ-WAIT"

            with m.State("READ-WAIT"):
                m.d.comb += [
                    self.o.eq(1),
                ]
                with m.If(self.drp.rdy):
                    m.d.ss += [
                        saved_val.eq(self.drp.do)
                    ]
                    m.next = "WRITE"

            with m.State("WRITE"):
                m.d.comb += [
                    self.o.eq(1),
                ]
                m.d.comb += [
                    self.drp.di.eq(saved_val),
                    self.drp.di[11].eq(0),
                    self.drp.we.eq(1),
                    self.drp.en.eq(1),
                ]
                m.next = "WRITE-WAIT"

            with m.State("WRITE-WAIT"):
                m.d.comb += [
                    self.o.eq(1),
                ]
                with m.If(self.drp.rdy):
                    m.next = "RESET-WAIT"

            with m.State("RESET-WAIT"):
                m.d.comb += [
                    self.o.eq(1),
                ]
                with m.If(~self.i):
                    m.next = "RXPMARESETDONE-WAIT"

            with m.State("RXPMARESETDONE-WAIT"):
                with m.If(self.rxpmaresetdone):
                    m.next = "RESTORE"
                with m.If(self.i):
                    m.next = "READ"

            with m.State("RESTORE"):
                with m.If(~self.rxpmaresetdone):
                    m.d.comb += [
                        self.drp.di.eq(saved_val),
                        self.drp.we.eq(1),
                        self.drp.en.eq(1),
                    ]
                    m.next = "RESTORE-WAIT"
                with m.If(self.i):
                    m.next = "READ"

            with m.State("RESTORE-WAIT"):
                with m.If(self.drp.rdy):
                    m.next = "IDLE"
                with m.If(self.i):
                    m.next = "READ"

        return m


# Unlike e.g. Lattice ECP5 series, Xilinx's SerDes do not have a direct path from
# the high-speed pads to the fabric; which makes detecting out-of-band signaling
# challenging. As an (undocumented) alternative to the method described below, on
# GTX transceivers, when the RXQPIEN input is driven high, the RXQPISENP/RXQPISENN
# outputs are connected to (single-ended) input buffers for the corresponding pad,
# and can be used from the fabric. On GTP transceivers these ports also exist,
# under different names: PMARSVDOUT0/PMARSVDOUT1 and PMARSVDIN2, respectively.

class GTOOBClockDivider(Elaboratable):
    """ Gateware that derives a clock for the out-of-band detector suitable for demodulating LFPS signaling. """

    # Out-of-band decoding requires an auxiliary clock with a specific frequency.
    # [UG482] does not describe how the Series 7 GTX OOB detector functions; however,
    # [UG196] describes in detail how the Virtex-5 GTP OOB detector works, which closely
    # matches the observable behavior of the GTX block.
    #
    # The input of the OOB detector is first processed through a peak detector, and then
    # sampled on both edges of a user-provided clock. The link is considered idle at
    # any time when the three last sampling intervals contained no transitions.
    #
    # LFPS sequences consist of alternating square wave bursts and periods of electrical
    # idle. If the clock driving the OOB detector is slow enough that the longest allowed
    # LFPS half-period is longer than three sampling intervals, then an LFPS sequence will
    # be demodulated by the OOB detector; RXELECIDLE will be low during the burst, and
    # high during the remainder of the repeat period.

    def __init__(self, ss_clock_frequency, max_pulse_period=_LFPS_PERIOD_MAX):
        # The generated clock must sample each half-period less than three times;
        # so that no matter how the OOB detector clock aligns with the LFPS waveform,
        # there would always be a transition.
        self._ratio = ceil((ss_clock_frequency * 3) * (max_pulse_period / 2))

        self.o = Signal()


    def elaborate(self, platform):
        m = Module()

        counter = Signal(range(self._ratio))

        m.d.ss += counter.eq(counter + 1)
        with m.If(counter + 1 == self._ratio):
            m.d.ss += [
                counter.eq(0),
                self.o.eq(~self.o)
            ]

        return m
