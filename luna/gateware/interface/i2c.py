# amaranth: UnusedElaboratable=no
#
# This file is part of LUNA.
#
# Copyright (c) 2023 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
#
# Based on I2C code from Glasgow
# I2C reference: https://www.nxp.com/docs/en/user-guide/UM10204.pdf

from amaranth import Elaboratable, Module, Signal, Cat, C
from amaranth.lib.cdc import FFSynchronizer
from amaranth.hdl.rec import Record, DIR_FANIN, DIR_FANOUT


__all__ = ["I2CBus", "I2CInitiator", "I2CRegisterInterface"]

class I2CBus(Record):
    """ Record representing an I2C bus. """
    def __init__(self):
        super().__init__([
            ('scl', [('i', 1, DIR_FANIN), ('o', 1, DIR_FANOUT), ('oe', 1, DIR_FANOUT)]),
            ('sda', [('i', 1, DIR_FANIN), ('o', 1, DIR_FANOUT), ('oe', 1, DIR_FANOUT)]),
        ])

class I2CRegisterInterface(Elaboratable):
    """ Gateware interface that handles I2C register reads and writes.

    I/O ports:

        # Controller signals:
        O: busy              -- indicates when the interface is busy processing a transaction
        I: address[8]        -- the address of the register to work with
        O: done              -- strobe that indicates when a register request is complete

        I: read_request      -- strobe that requests a register read
        O: read_data[8]      -- data read from the relevant register read

        I: write_request     -- strobe that indicates a register write
        I: write_data[8]     -- data to be written during a register write

    """
    def __init__(self, pads, *, period_cyc, address, clk_stretch=False, data_bytes=1):

        self.pads          = pads
        self.period_cyc    = period_cyc
        self.dev_address   = address
        self.clk_stretch   = clk_stretch

        # I/O ports

        self.busy          = Signal()
        self.address       = Signal(8)
        self.size          = Signal(range(data_bytes+1))
        self.done          = Signal()

        self.read_request  = Signal()
        self.read_data     = Signal(8 * data_bytes)

        self.write_request = Signal()
        self.write_data    = Signal(8 * data_bytes)

    def elaborate(self, platform):
        m = Module()

        current_address = Signal.like(self.address, reset_less=True)
        current_write   = Signal.like(self.write_data, reset_less=True)
        current_read    = Signal.like(self.read_data - 8, reset_less=True)
        rem_bytes       = Signal.like(self.size, reset_less=True)
        is_write        = Signal(reset_less=True)

        # I2C initiator (low level manager) and default signal values
        m.submodules.i2c = i2c = I2CInitiator(pads=self.pads, period_cyc=self.period_cyc, clk_stretch=self.clk_stretch)
        m.d.comb += [
            i2c.start .eq(0),
            i2c.write .eq(0),
            i2c.read  .eq(0),
            i2c.stop  .eq(0),
        ]

        with m.FSM() as fsm:

            # We're busy whenever we're not IDLE; indicate so.
            m.d.comb += self.busy.eq(~fsm.ongoing('IDLE'))

            # IDLE: wait for a request to be made
            with m.State('IDLE'):
                with m.If(self.read_request | self.write_request):
                    m.d.sync += [
                        current_address .eq(self.address),
                        current_write   .eq(self.write_data),
                        current_read    .eq(0),
                        rem_bytes       .eq(self.size),
                        is_write        .eq(self.write_request),
                    ]
                    m.next = 'START'

            # Common device and register address handling
            with m.State('START'):
                with m.If(~i2c.busy):
                    m.d.comb += i2c.start.eq(1)
                    m.next = 'SEND_DEV_ADDRESS'

            with m.State("SEND_DEV_ADDRESS"):
                with m.If(~i2c.busy):
                    m.d.comb += [
                        i2c.data_i.eq((self.dev_address << 1) | 0),
                        i2c.write .eq(1),
                    ]
                    m.next = "ACK_DEV_ADDRESS"

            with m.State("ACK_DEV_ADDRESS"):
                with m.If(~i2c.busy):
                    with m.If(i2c.ack_o):  # dev address asserted
                        m.next = "SEND_REG_ADDRESS"
                    with m.Else():
                        m.next = "ABORT"

            with m.State("SEND_REG_ADDRESS"):
                with m.If(~i2c.busy):
                    m.d.comb += [
                        i2c.data_i.eq(current_address),
                        i2c.write .eq(1),
                    ]
                    m.next = "ACK_REG_ADDRESS"

            with m.State("ACK_REG_ADDRESS"):
                with m.If(~i2c.busy):
                    with m.If(~i2c.ack_o):
                        m.next = "ABORT"   # register address not asserted
                    with m.Elif(rem_bytes == 0):
                        m.next = "FINISH"  # 0-byte read/write
                    with m.Elif(is_write):
                        m.next = "WR_SEND_VALUE"
                    with m.Else():
                        m.next = "RD_START"

            # Write states
            # These handle the transmission of the successive bytes in the 
            # current write request

            with m.State("WR_SEND_VALUE"):
                with m.If(~i2c.busy):
                    m.d.comb += [
                        i2c.data_i.eq(current_write[-8:]),
                        i2c.write .eq(1),
                    ]
                    # prepare next byte too
                    m.d.sync += [
                        current_write.eq(current_write << 8),
                        rem_bytes    .eq(rem_bytes - 1),
                    ]
                    m.next = "WR_ACK_VALUE"
            
            with m.State("WR_ACK_VALUE"):
                with m.If(~i2c.busy):
                    with m.If(~i2c.ack_o):
                        m.next = "ABORT"
                    with m.Elif(rem_bytes == 0):
                        m.next = "FINISH"
                    with m.Else():
                        m.next = "WR_SEND_VALUE"

            # Read states
            # Once the source register address is written in the common states,
            # the following handles the retrieval of bytes from the device with
            # a new I2C read request.

            with m.State('RD_START'):
                with m.If(~i2c.busy):
                    m.d.comb += i2c.start.eq(1)
                    m.next = 'RD_SEND_DEV_ADDRESS'

            with m.State("RD_SEND_DEV_ADDRESS"):
                with m.If(~i2c.busy):
                    m.d.comb += [
                        i2c.data_i.eq((self.dev_address << 1) | 1),
                        i2c.write .eq(1),
                    ]
                    m.next = "RD_ACK_DEV_ADDRESS"

            with m.State("RD_ACK_DEV_ADDRESS"):
                with m.If(~i2c.busy):
                    with m.If(i2c.ack_o):  # dev address asserted
                        m.next = "RD_RECV_VALUE"
                    with m.Else():
                        m.next = "ABORT"

            with m.State("RD_RECV_VALUE"):
                with m.If(~i2c.busy):
                    m.d.comb += [
                        i2c.ack_i.eq(~(rem_bytes == 1)),  # 0 in last read byte
                        i2c.read .eq(1),
                    ]
                    m.d.sync += rem_bytes.eq(rem_bytes - 1)
                    m.next = "RD_WAIT_VALUE"

            with m.State("RD_WAIT_VALUE"):
                with m.If(~i2c.busy):
                    m.d.sync += current_read.eq((current_read << 8) | i2c.data_o)
                    with m.If(rem_bytes == 0):
                        m.d.sync += self.read_data.eq((current_read << 8) | i2c.data_o)
                        m.next = "FINISH"
                    with m.Else():
                        m.next = "RD_RECV_VALUE"

            # Common "exit" states that return to idle
            # FINISH asserts "done" to tell the transfer was done successfully
            with m.State("FINISH"):
                with m.If(~i2c.busy):
                    m.d.comb += [
                        i2c.stop .eq(1),
                        self.done.eq(1),
                    ]
                    m.next = "IDLE"
            
            with m.State("ABORT"):
                with m.If(~i2c.busy):
                    m.d.comb += i2c.stop .eq(1)
                    m.next = "IDLE"

        return m


class I2CBusDriver(Elaboratable):
    """
    Decodes bus conditions (start, stop, sample and setup) and provides synchronization.
    """
    def __init__(self, pads):
        self.scl_t  = pads.scl_t if hasattr(pads, "scl_t") else pads.scl
        self.sda_t  = pads.sda_t if hasattr(pads, "sda_t") else pads.sda

        self.scl_i  = Signal()
        self.scl_o  = Signal(reset=1)
        self.sda_i  = Signal()
        self.sda_o  = Signal(reset=1)

        self.sample = Signal(name="bus_sample")
        self.setup  = Signal(name="bus_setup")
        self.start  = Signal(name="bus_start")
        self.stop   = Signal(name="bus_stop")

    def elaborate(self, platform):
        m = Module()

        # SDA line must be bidirectional...
        m.d.comb += [
            self.sda_t.o  .eq(0),
            self.sda_t.oe .eq(~self.sda_o),
        ]
        m.submodules += FFSynchronizer(self.sda_t.i, self.sda_i, reset=1)

        # But the SCL line does not need to: only if we want to support clock stretching
        if hasattr(self.scl_t, "oe"):
            m.d.comb += [
                self.scl_t.o  .eq(0),
                self.scl_t.oe .eq(~self.scl_o),
            ]
            m.submodules += FFSynchronizer(self.scl_t.i, self.scl_i, reset=1)
        else:
            # SCL output only
            m.d.comb += [
                self.scl_t.o  .eq(self.scl_o),
                self.scl_i    .eq(self.scl_o),
            ]

        # Additional signals for bus state detection
        scl_r = Signal(reset=1)
        sda_r = Signal(reset=1)
        m.d.sync += [
            scl_r.eq(self.scl_i),
            sda_r.eq(self.sda_i),
        ]
        m.d.comb += [
            self.sample .eq(~scl_r & self.scl_i),  # SCL rising edge
            self.setup  .eq(scl_r & ~self.scl_i),  # SCL falling edge
            self.start  .eq(self.scl_i & sda_r & ~self.sda_i),  # SDA fall, SCL high
            self.stop   .eq(self.scl_i & ~sda_r & self.sda_i),  # SDA rise, SCL high
        ]
        
        return m


class I2CInitiator(Elaboratable):
    """
    Simple I2C transaction initiator.

    Generates start and stop conditions, and transmits and receives octets.
    Clock stretching is supported.

    :param period_cyc:
        Bus clock period, as a multiple of system clock period.
    :type period_cyc: int
    :param clk_stretch:
        If true, SCL will be monitored for devices stretching the clock. Otherwise,
        only internally generated SCL is considered.
    :type clk_stretch: bool

    :attr busy:
        Busy flag. Low if the state machine is idle, high otherwise.
    :attr start:
        Start strobe. When ``busy`` is low, asserting ``start`` for one cycle generates
        a start or repeated start condition on the bus. Ignored when ``busy`` is high.
    :attr stop:
        Stop strobe. When ``busy`` is low, asserting ``stop`` for one cycle generates
        a stop condition on the bus. Ignored when ``busy`` is high.
    :attr write:
        Write strobe. When ``busy`` is low, asserting ``write`` for one cycle latches
        ``data_i`` and transmits it on the bus, after which the acknowledge bit
        from the bus is latched to ``ack_o``. Ignored when ``busy`` is high.
    :attr data_i:
        Data octet to be transmitted. Latched immediately after ``write`` is asserted.
    :attr ack_o:
        Received acknowledge bit.
    :attr read:
        Read strobe. 
        When ``busy`` is low, asserting ``read`` for one cycle receives an octet on 
        the bus and latches it to ``data_o``, after which the acknowledge bit is 
        asserted if ``ack_i`` is high. Ignored when ``busy`` is high.
    :attr data_o:
        Received data octet.
    :attr ack_i:
        Acknowledge bit to be transmitted. Latched immediately after ``read`` is asserted.
    """
    def __init__(self, pads, period_cyc, clk_stretch=True):
        self.bus         = I2CBusDriver(pads)
        self.period_cyc  = int(period_cyc)
        self.clk_stretch = clk_stretch

        self.busy   = Signal(reset=1)
        self.start  = Signal()
        self.stop   = Signal()
        self.read   = Signal()
        self.data_i = Signal(8)
        self.ack_o  = Signal()
        self.write  = Signal()
        self.data_o = Signal(8)
        self.ack_i  = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = bus = self.bus

        timer = Signal(range(self.period_cyc))
        stb   = Signal()

        with m.If((timer == 0) | ~self.busy):
            m.d.sync += timer.eq(self.period_cyc // 4)
        with m.Elif((not self.clk_stretch) | (bus.scl_o == bus.scl_i)):
            m.d.sync += timer.eq(timer - 1)

        m.d.comb += stb.eq(timer == 0)

        bitno   = Signal(range(8))
        r_shreg = Signal(8)
        w_shreg = Signal(8)
        r_ack   = Signal()
        
        with m.FSM() as fsm:
            self._fsm = fsm
            def scl_l(state, next_state, *exprs):
                with m.State(state):
                    with m.If(stb):
                        m.d.sync += self.bus.scl_o.eq(0)
                        m.next = next_state
                        m.d.sync += exprs

            def scl_h(state, next_state, *exprs):
                with m.State(state):
                    with m.If(stb):
                        m.d.sync += self.bus.scl_o.eq(1)
                    with m.Elif(self.bus.scl_o == 1):
                        with m.If((not self.clk_stretch) | (self.bus.scl_i == 1)):
                            m.next = next_state
                            m.d.sync += exprs

            def stb_x(state, next_state, *exprs, bit7_next_state=None):
                with m.State(state):
                    with m.If(stb):
                        m.next = next_state
                        if bit7_next_state is not None:
                            with m.If(bitno == 7):
                                m.next = bit7_next_state
                        m.d.sync += exprs

            with m.State("IDLE"):
                m.d.sync += self.busy.eq(1)
                with m.If(self.start):
                    with m.If(bus.scl_i & bus.sda_i):
                        m.next = "START-SDA-L"
                    with m.Elif(~bus.scl_i):
                        m.next = "START-SCL-H"
                    with m.Elif(bus.scl_i):
                        m.next = "START-SCL-L"
                with m.Elif(self.stop):
                    with m.If(bus.scl_i & ~bus.sda_o):
                        m.next = "STOP-SDA-H"
                    with m.Elif(~bus.scl_i):
                        m.next = "STOP-SCL-H"
                    with m.Elif(bus.scl_i):
                        m.next = "STOP-SCL-L"
                with m.Elif(self.write):
                    m.d.sync += w_shreg.eq(self.data_i)
                    m.next = "WRITE-DATA-SCL-L"
                with m.Elif(self.read):
                    m.d.sync += r_ack.eq(self.ack_i)
                    m.next = "READ-DATA-SCL-L"
                with m.Else():
                    m.d.sync += self.busy.eq(0)
            
            # start
            scl_l("START-SCL-L", "START-SDA-H")
            stb_x("START-SDA-H", "START-SCL-H",
                self.bus.sda_o.eq(1)
            )
            scl_h("START-SCL-H", "START-SDA-L")
            stb_x("START-SDA-L", "IDLE",
                self.bus.sda_o.eq(0)
            )
            # stop
            scl_l("STOP-SCL-L",  "STOP-SDA-L")
            stb_x("STOP-SDA-L",  "STOP-SCL-H",
                self.bus.sda_o.eq(0)
            )
            scl_h("STOP-SCL-H",  "STOP-SDA-H")
            stb_x("STOP-SDA-H",  "IDLE",
                self.bus.sda_o.eq(1)
            )
            # write data
            scl_l("WRITE-DATA-SCL-L", "WRITE-DATA-SDA-X")
            stb_x("WRITE-DATA-SDA-X", "WRITE-DATA-SCL-H",
                self.bus.sda_o.eq(w_shreg[7])
            )
            scl_h("WRITE-DATA-SCL-H", "WRITE-DATA-SDA-N",
                w_shreg.eq(Cat(C(0, 1), w_shreg[0:7]))
            )
            stb_x("WRITE-DATA-SDA-N", "WRITE-DATA-SCL-L",
                bitno.eq(bitno + 1),
                bit7_next_state="WRITE-ACK-SCL-L"
            )
            # write ack
            scl_l("WRITE-ACK-SCL-L", "WRITE-ACK-SDA-H")
            stb_x("WRITE-ACK-SDA-H", "WRITE-ACK-SCL-H",
                self.bus.sda_o.eq(1)
            )
            scl_h("WRITE-ACK-SCL-H", "WRITE-ACK-SDA-N",
                self.ack_o.eq(~self.bus.sda_i)
            )
            stb_x("WRITE-ACK-SDA-N", "IDLE")
            # read data
            scl_l("READ-DATA-SCL-L", "READ-DATA-SDA-H")
            stb_x("READ-DATA-SDA-H", "READ-DATA-SCL-H",
                self.bus.sda_o.eq(1)
            )
            scl_h("READ-DATA-SCL-H", "READ-DATA-SDA-N",
                r_shreg.eq(Cat(self.bus.sda_i, r_shreg[0:7]))
            )
            stb_x("READ-DATA-SDA-N", "READ-DATA-SCL-L",
                bitno.eq(bitno + 1),
                bit7_next_state="READ-ACK-SCL-L"
            )
            # read ack
            scl_l("READ-ACK-SCL-L", "READ-ACK-SDA-X")
            stb_x("READ-ACK-SDA-X", "READ-ACK-SCL-H",
                self.bus.sda_o.eq(~r_ack)
            )
            scl_h("READ-ACK-SCL-H", "READ-ACK-SDA-N",
                self.data_o.eq(r_shreg)
            )
            stb_x("READ-ACK-SDA-N", "IDLE")

        return m

