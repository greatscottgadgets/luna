#
# This file is part of LUNA.
#
""" UTMI interfacing. """


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
