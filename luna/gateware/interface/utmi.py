#
# This file is part of LUNA.
#
""" UTMI interfacing. """


from nmigen         import Elaboratable, Signal, Module
from nmigen.hdl.rec import Record, DIR_FANIN, DIR_FANOUT


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


class UTMIInterfaceMultiplexer(Elaboratable):
    """ Gateware that merges a collection of UTMITransmitInterfaces into a single interface.

    Assumes that only one transmitter will be communicating at once.

    I/O port:
        O*: output -- Our output interface; has all of the active busses merged together.
    """

    def __init__(self):

        # Collection that stores each of the interfaces added to this bus.
        self._inputs = []

        #
        # I/O port
        #
        self.output = UTMITransmitInterface()


    def add_input(self, input_interface : UTMITransmitInterface):
        """ Adds a transmit interface to the multiplexer. """
        self._inputs.append(input_interface)


    def elaborate(self, platform):
        m = Module()

        #
        # Our basic functionality is simple: we'll build a priority encoder that
        # connects whichever interface has its .valid signal high.
        #

        conditional = m.If

        for interface in self._inputs:

            # If the given interface is asserted, drive our output with its signals.
            with conditional(interface.valid):
                m.d.comb += interface.connect(self.output)

            # After our first iteration, use Elif instead of If.
            conditional = m.Elif


        return m



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
            ('line_state',                  1),
            ('vbus_valid',                  1),
            ('session_valid',               1),
            ('session_end',                 1),
            ('rx_error',                    1),
            ('host_disconnect',             1),
            ('id_digital',                  1)
        ])
