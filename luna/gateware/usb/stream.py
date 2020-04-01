#
# This file is part of LUNA.
#
""" Core stream definitions. """

from nmigen         import Elaboratable, Signal, Module
from nmigen.hdl.rec import Record, DIR_FANIN, DIR_FANOUT

from ..stream       import StreamInterface


class USBInStreamInterface(StreamInterface):
    """ Variant of LUNA's StreamInterface optimized for USB IN transmission.

    This stream interface is nearly identical to StreamInterface, with the following
    restriction: the `valid` signal _must_ be held high for every packet between `first`
    and `last`, inclusively.

    This means that the relevant interface can easily be translated to the UTMI transmit
    signals, with the following mappings:

        Stream  | UTMI
        --------|-----------
        valid   | tx_valid
        payload | tx_data
        ready   | tx_ready
    """

    def bridge_to(self, utmi_tx):
        """ Generates a list of connections that connect this stream to the provided UTMITransmitInterface. """

        return [
            utmi_tx.valid  .eq(self.valid),
            utmi_tx.data   .eq(self.payload),

            self.ready     .eq(utmi_tx.ready)
        ]



class USBOutStreamInterface(StreamInterface):
    """ Variant of LUNA's StreamInterface optimized for USB OUT receipt.

    This stream interface is nearly identical to StreamInterface, but the 'ready'
    signal is removed.

    This means that the relevant interface can easily be translated to the UTMI receive
    signals, with the following mappings:

        UTMI     | Stream
        ---------|-----------
        rx_data  | payload
        rx_valid | valid
    """


    def __init__(self, payload_width=8):
        """
        Parameter:
            payload_width -- The width of the payload packets.
        """
        Record.__init__(self, [
            ('valid',    1,             DIR_FANOUT),

            ('first',    1,             DIR_FANIN),
            ('last',     1,             DIR_FANIN),

            ('payload',  payload_width, DIR_FANIN),
        ])
