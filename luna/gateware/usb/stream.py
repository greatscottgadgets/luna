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



class USBOutStreamInterface(Record):
    """ Variant of LUNA's StreamInterface optimized for USB OUT receipt.

    This is a heavily simplified version of our StreamInterface, which omits the 'first',
    'last', and 'ready' signals. Instead, the streamer indicates when data is valid using
    the 'next' signal; and the receiver must keep times.

    This is selected so the relevant interface can easily be translated to the UTMI receive
    signals, with the following mappings:

        UTMI      | Stream
        --------- |-----------
        rx_active | valid
        rx_data   | payload
        rx_valid  | next

    """

    def __init__(self, payload_width=8):
        """
        Parameter:
            payload_width -- The width of the payload packets.
        """
        super().__init__([
            ('valid',    1,             DIR_FANOUT),
            ('next',     1,             DIR_FANOUT),

            ('payload',  payload_width, DIR_FANOUT),
        ])


    def bridge_to(self, utmi_rx):
        """ Generates a list of connections that connect this stream to the provided UTMIReceiveInterface. """

        return [
            self.valid     .eq(utmi_rx.rx_active),
            self.next      .eq(utmi_rx.rx_valid),
            self.data      .eq(utmi_rx.payload)
        ]
