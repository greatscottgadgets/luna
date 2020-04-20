#
# This file is part of LUNA.
#
""" Gateware that assists with endpoint transactions. """

from nmigen         import Signal, Elaboratable, Module

from .packet        import HandshakeExchangeInterface
from ..stream       import USBInStreamInterface


class USBInTransferManager(Elaboratable):
    """ Module that sequences USB IN packets, creating a longer transfer.

    I/O port:

        # Core data interface.
        I: send_packet      -- Strobe that triggers a packet to be sent, if one is
                               available, or a NAK if none is available. Usually pulsed
                               an inter-packet delay after an IN token.
        *: data_stream      -- Input stream; accepts data to be sent on the endpoint.
        *: packet_stream    -- Output stream; broken into packets to be sent.
        *: handshakes_out   -- Output that carries handshake packet requests.
        O: data_pid[2]      -- The data pid value to be carried to our transmitter.


        # Control interface.
        I: generate_zlps    -- If high, zero-length packets will automatically be generated
                               if the end of a transfer would not result in a short packet.
                               (This should be set for control endpoints; and for any interface
                               where transfer boundaries are significant.)

        I: start_with_data1 -- If high, the transmitter will start our PID with DATA1.
        I: reset_sequence   -- If true, our PID generated will reset to the value indicated by
                               `start_with_data1`. If desired, this can be held permanently high
                               to control our PID expectation manually.

    """

    def __init__(self, max_packet_size):
        """
        Parmaters:
            max_packet_size -- The maximum packet size for our associated endpoint, as an integer.
        """

        self._max_packet_size = max_packet_size

        #
        # I/O port
        #
        self.send_packet      = Signal()
        self.data_stream      = USBInStreamInterface()
        self.packet_stream    = USBInStreamInterface()
        self.handshakes_out   = HandshakeExchangeInterface(is_detector=False)
        self.data_pid         = Signal(2)

        self.generate_zlps    = Signal()
        self.start_with_data1 = Signal()
        self.reset_sequence   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Store the LSB of our PID sequence.
        # We'll track only 0 (DATA0) vs 1 (DATA1).
        expected_pid = Signal()

        # Handle our PID-sequence reset.
        with m.If(self.reset_sequence):
            m.d.usb += expected_pid.eq(self.start_with_data1)

        # Track how many bytes remain in the current packet.
        packet_bytes_remaining = Signal(range(0, self._max_packet_size + 1))


        with m.FSM(domain='usb'):

            # IDLE -- we're not currently transmitting; and instead are waiting for data to
            # become present on our data stream
            with m.State('IDLE'):
                pass



        return m
