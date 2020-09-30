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

WITH_ILA = True

class USBSuperSpeedExample(Elaboratable):
    """ Work-in-progress example/test fixture for a SuperSpeed device. """


    def __init__(self):
        if WITH_ILA:
            self.ila_data             = Signal(32)
            self.ila_ctrl             = Signal(4)
            self.ila_valid            = Signal()

            self.ila = USBIntegratedLogicAnalyer(
                bus="usb",
                domain="ss",
                signals=[
                    self.ila_data,
                    self.ila_ctrl,
                    self.ila_valid,
                ],
                sample_depth=512,
                max_packet_size=64,
                samples_pretrigger=16
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
        m.submodules.usb = usb = USBSuperSpeedDevice(phy=phy, sync_frequency=50e6)


        # Heartbeat LED.
        counter = Signal(28)
        m.d.ss += counter.eq(counter + 1)

        m.d.comb += [
            platform.get_led(m, 0).o.eq(usb.link_trained),

            # Heartbeat.
            platform.get_led(m, 7).o.eq(counter[-1])
        ]



        if WITH_ILA:
            m.d.comb += [
                # ILA
                self.ila_data        .eq(usb.rx_data_tap.data),
                self.ila_ctrl        .eq(usb.rx_data_tap.ctrl),
                self.ila_valid       .eq(usb.rx_data_tap.valid),
                self.ila.trigger     .eq(usb.link_trained)
            ]

        # Return our elaborated module.
        return m


if __name__ == "__main__":
    ex = top_level_cli(USBSuperSpeedExample)
    if WITH_ILA:
        ex.emit()
