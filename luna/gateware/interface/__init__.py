#
# This file is part of LUNA.
#
""" Interface code helpers. """

from nmigen.hdl.rec import Record, DIR_FANIN, DIR_FANOUT

class StreamInterface(Record):
    """ Simple record implementing a unidirectional data stream.

    This class is similar to LiteX's streams; but instances may be optimized for
    interaction with USB PHYs. Accordingly, some modules may add restrictions; this
    is typically indicated by subclassing this interface.

    In the following signals list, 'T' indicates a signal driven by the sender;
    and 'R' indicates a signal driven by the receiver.

    Signals:
        T: valid      -- Indicates that an active transaction is underway. For LUNA connections,
                         this must go high with `first`, and remain high until the cycle after `last`.
        T: first      -- Indicates that the payload byte is the first byte of a new packet.
        T: last       -- Indicates that the payload byte is the last byte of the current packet.
        T: payload[]  -- The data payload to be transmitted.

        R: ready      -- Indicates that the receiver will accept the payload byte at the next active
                         clock edge. Can be de-asserted to slew the transmitter.
    """


    def __init__(self, payload_width=8):
        """
        Parameter:
            payload_width -- The width of the payload packets.
        """
        super().__init__([
            ('valid',    1,             DIR_FANIN),
            ('ready',    1,             DIR_FANOUT),

            ('first',    1,             DIR_FANIN),
            ('last',     1,             DIR_FANIN),

            ('payload',  payload_width, DIR_FANIN),
        ])



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
