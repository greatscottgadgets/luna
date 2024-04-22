#
# This file is part of LUNA.
#
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
from luna.gateware.interface.spi import SPIGatewareTestCase
from luna.gateware.test import LunaGatewareTestCase, sync_test_case

from amaranth import Signal
from luna.gateware.interface.i2c import I2CBus, I2CInitiator

class I2CInitiatorTestbench(I2CInitiator):
    def __init__(self, pads, period_cyc, clk_stretch=True):
        super().__init__(pads, period_cyc, clk_stretch)
        self.scl_o = Signal(reset=1)  # used to override values from testbench
        self.sda_o = Signal(reset=1)  

    def elaborate(self, platform):
        m = super().elaborate(platform)
        m.d.comb += [
            self.bus.scl_t.i.eq((self.bus.scl_t.o | ~self.bus.scl_t.oe) & self.scl_o),
            self.bus.sda_t.i.eq((self.bus.sda_t.o | ~self.bus.sda_t.oe) & self.sda_o),
        ]
        return m


class TestI2CInitiator(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = I2CInitiatorTestbench
    FRAGMENT_ARGUMENTS = { "pads": I2CBus(), "period_cyc": 16 }

    def wait_condition(self, strobe):
        yield from self.wait_until(strobe, timeout=3*self.dut.period_cyc)

    def start(self):
        yield from self.pulse(self.dut.start)
        yield from self.wait_condition(self.dut.bus.start)

    def stop(self):
        yield from self.pulse(self.dut.stop)
        yield from self.wait_condition(self.dut.bus.stop)
    
    @sync_test_case
    def test_start(self):
        yield from self.start()
        self.assertEqual((yield self.dut.busy), 0)

    @sync_test_case
    def test_repeated_start(self):
        yield self.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.start()
        yield from self.wait_condition(self.dut.bus.start)
        self.assertEqual((yield self.dut.busy), 0)

    @sync_test_case
    def test_stop(self):
        yield self.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.stop()
        self.assertEqual((yield self.dut.busy), 0)

    def write(self, data, bits, ack):
        yield self.dut.data_i.eq(data)
        yield from self.pulse(self.dut.write)
        for n, bit in enumerate(bits):
            yield
            yield
            yield from self.wait_condition(self.dut.bus.scl_i == 0)
            yield from self.wait_condition(self.dut.bus.scl_i == 1)
            self.assertEqual((yield self.dut.bus.sda_i), bit)
            yield
        yield from self.advance_cycles(self.dut.period_cyc // 2)
        yield
        yield
        yield from self.wait_condition(self.dut.bus.scl_i == 0)
        yield self.dut.sda_o.eq(not ack)
        yield from self.wait_condition(self.dut.bus.scl_i == 1)
        yield self.dut.sda_o.eq(1)
        self.assertEqual((yield self.dut.busy), 1)
        yield from self.advance_cycles(self.dut.period_cyc // 2)
        yield
        yield
        yield
        yield
        self.assertEqual((yield self.dut.busy), 0)
        self.assertEqual((yield self.dut.ack_o), ack)

    @sync_test_case
    def test_write_ack(self):
        yield self.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.write(0xA5, [1, 0, 1, 0, 0, 1, 0, 1], 1)

    @sync_test_case
    def test_write_nak(self):
        yield self.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.write(0x5A, [0, 1, 0, 1, 1, 0, 1, 0], 0)

    @sync_test_case
    def test_write_tx(self):
        yield from self.start()
        yield from self.write(0x55, [0, 1, 0, 1, 0, 1, 0, 1], 1)
        yield from self.write(0x33, [0, 0, 1, 1, 0, 0, 1, 1], 0)
        yield from self.stop()
        yield
        yield
        self.assertEqual((yield self.dut.bus.sda_i), 1)
        self.assertEqual((yield self.dut.bus.scl_i), 1)

    def read(self, data, bits, ack):
        yield self.dut.ack_i.eq(ack)
        yield from self.pulse(self.dut.read)
        for n, bit in enumerate(bits):
            yield
            yield
            yield from self.wait_condition(self.dut.bus.scl_i == 0)
            yield self.dut.sda_o.eq(bit)
            yield from self.wait_condition(self.dut.bus.scl_i == 1)
            yield
        yield self.dut.sda_o.eq(1)
        yield from self.advance_cycles(self.dut.period_cyc // 2)
        yield
        yield
        yield from self.wait_condition(self.dut.bus.scl_i == 0)
        yield from self.wait_condition(self.dut.bus.scl_i == 1)
        self.assertEqual((yield self.dut.bus.sda_i), not ack)
        self.assertEqual((yield self.dut.busy), 1)
        yield from self.advance_cycles(self.dut.period_cyc // 2)
        yield
        yield
        yield
        yield
        self.assertEqual((yield self.dut.busy), 0)
        self.assertEqual((yield self.dut.data_o), data)

    @sync_test_case
    def test_read_ack(self):
        yield self.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.read(0xA5, [1, 0, 1, 0, 0, 1, 0, 1], 1)

    @sync_test_case
    def test_read_nak(self):
        yield self.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.read(0x5A, [0, 1, 0, 1, 1, 0, 1, 0], 0)

    @sync_test_case
    def test_read_tx(self):
        yield from self.start()
        yield from self.read(0x55, [0, 1, 0, 1, 0, 1, 0, 1], 1)
        yield from self.read(0x33, [0, 0, 1, 1, 0, 0, 1, 1], 0)
        yield from self.stop()
        yield
        yield
        self.assertEqual((yield self.dut.bus.sda_i), 1)
        self.assertEqual((yield self.dut.bus.scl_i), 1)
