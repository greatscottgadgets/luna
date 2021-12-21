#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" UTMI interfacing. """

from enum import IntEnum

from amaranth       import Elaboratable, Signal, Module
from amaranth.hdl.rec import Record, DIR_FANIN, DIR_FANOUT

from ..utils.bus    import OneHotMultiplexer

class UTMIOperatingMode:
    """ Enumeration that specifies the modes a UTMI transceiver can use. """

    NORMAL                    = 0
    NON_DRIVING               = 1

    RAW_DRIVE                 = 2
    DISABLE_BITSTUFF_AND_NRZI = 2
    CHIRP                     = 2

    NO_SYNC_OR_EOP            = 3


class UTMITerminationSelect:
    """ Enumeration that specifies meanings of the UTMI TermSelect bit. """

    HS_NORMAL    = 0
    HS_CHIRP     = 1
    LS_FS_NORMAL = 1


class UTMITransmitInterface(Record):
    """ Interface present on hardware that transmits onto a UTMI bus. """

    LAYOUT = [

        # Indicates when the data on tx_data is valid.
        ('valid', 1, DIR_FANOUT),

        # The data to be transmitted.
        ('data',  8, DIR_FANOUT),

        # Pulsed by the UTMI bus when the given data byte will be accepted
        # at the next clock edge.
        ('ready', 1, DIR_FANIN),
    ]

    def __init__(self):
        super().__init__(self.LAYOUT)


    def attach(self, utmi_bus):
        """ Returns a list of connection fragments connecting this interface to the provided bus.

        A typical usage might look like:
            m.d.comb += interface_object.attach(utmi_bus)
        """

        return [
            utmi_bus.tx_data   .eq(self.data),
            utmi_bus.tx_valid  .eq(self.valid),

            self.ready          .eq(utmi_bus.tx_ready),
        ]


class UTMIInterfaceMultiplexer(OneHotMultiplexer):
    """ Gateware that merges a collection of UTMITransmitInterfaces into a single interface.

    Assumes that only one transmitter will be communicating at once.

    I/O port:
        O*: output -- Our output interface; has all of the active busses merged together.
    """

    def __init__(self):
        super().__init__(
            interface_type=UTMITransmitInterface,
            mux_signals= ('data',),
            or_signals=  ('valid',),
            pass_signals=('ready',)
        )




class UTMIInterface(Record):
    """ UTMI+-standardized interface. Intended mostly as a simulation aid."""

    def __init__(self):
        super().__init__([
            # Core signals.
            ("rx_data",                     8),
            ("rx_active",                   1),
            ("rx_valid",                    1),

            ("tx_data",                     8),
            ("tx_valid",                    1),
            ("tx_ready",                    1),

            # Control signals.
            ('xcvr_select',                 2),
            ('term_select',                 1),
            ('op_mode',                     2),
            ('suspend',                     1),
            ('id_pullup',                   1),
            ('dm_pulldown',                 1),
            ('dp_pulldown',                 1),
            ('chrg_vbus',                   1),
            ('dischrg_vbus',                1),
            ('use_external_vbus_indicator', 1),

            # Event signals.
            ('line_state',                  2),
            ('vbus_valid',                  1),
            ('session_valid',               1),
            ('session_end',                 1),
            ('rx_error',                    1),
            ('host_disconnect',             1),
            ('id_digital',                  1)
        ])
