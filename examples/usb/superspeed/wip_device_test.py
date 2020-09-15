#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
""" Incomplete example for working the SerDes-based a PIPE PHY. """

from nmigen import *

from luna                          import top_level_cli
from luna.gateware.platform        import NullPin
from luna.gateware.usb.devices.ila import USBIntegratedLogicAnalyer, USBIntegratedLogicAnalyzerFrontend

from luna.usb3                     import USBSuperSpeedDevice

WITH_ILA = False

class USBSuperSpeedExample(Elaboratable):
    """ Work-in-progress example/test fixture for a SuperSpeed device. """


    def __init__(self):
        if WITH_ILA:
            self.serdes_rx = Signal(32)
            self.ctrl      = Signal(4)
            self.valid     = Signal()

            self.ila = USBIntegratedLogicAnalyer(
                bus="usb",
                domain="ss",
                signals=[
                    self.serdes_rx,
                    self.ctrl,
                    self.valid,
                ],
                sample_depth=128,
                max_packet_size=64
            )

    def emit(self):
        frontend = USBIntegratedLogicAnalyzerFrontend(ila=self.ila)
        frontend.emit_vcd("/tmp/output.vcd")

    def elaborate(self, platform):
        m = Module()
        if WITH_ILA:
            m.submodules.ila = self.ila

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our core PIPE PHY. Since PHY configuration is per-board, we'll just ask
        # our platform for a pre-configured USB3 PHY.
        m.submodules.phy = phy = platform.create_usb3_phy()

        # Create our core SuperSpeed device.
        m.submodules.usb = USBSuperSpeedDevice(phy=phy)

        if WITH_ILA:
            m.d.comb += [
                # ILA
                self.serdes_rx    .eq(phy.source.data),
                self.ctrl         .eq(phy.source.ctrl),
                self.valid        .eq(phy.source.valid),
                self.ila.trigger  .eq(phy.source.data.word_select(3, 8) == 0xbc)
            ]

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    ex = top_level_cli(USBSuperSpeedExample)
    if WITH_ILA:
        ex.emit()
