#
# This file is part of LUNA.
#
""" UTMI interfacing. """


from nmigen.hdl.rec import Record, DIR_FANIN, DIR_FANOUT


class UTMITransmitInterface(Record):
    """ Interface present on hardware that transmits onto a UTMI bus. """

    LAYOUT = [

        # Indicates when the data on tx_data is valid.
        ('tx_valid', 1, DIR_FANOUT),

        # The data to be transmitted.
        ('tx_data',  8, DIR_FANOUT),

        # Pulsed by the UTMI bus when the given data byte will be accepted
        # at the next clock edge.
        ('tx_ready', 1, DIR_FANIN),
    ]


    def __init__(self):
        super().__init__(self.LAYOUT)
