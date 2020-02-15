#
# This file is part of LUNA.
#
""" UART interface gateware."""

import unittest

from abc import ABCMeta
from enum import Enum, auto
from nmigen import Elaboratable, Module, Signal, Cat

from ..test import LunaGatewareTestCase, sync_test_case


class UARTTransmitter(Elaboratable):
    """ Simple UART transitter.

    Intended for communicating with the debug controller; currently assumes 8n1.

    I/O:
        O: tx          -- The UART output.

        I: data        -- The byte to be sent. Latched in at the start of each frame.
        I: send        -- When asserted, the transmitter will attempt to send a frame
                          of data. This can be pulsed when the transmitter is idle to send
                          a single byte; or held to continuosly stream data.

        O: accepted    -- Strobe that indicates when the `data` byte has been
                          latched in; and the next data byte can be presented.
        O: idle        -- Asserted when the transmitter is idle; and thus pulsing
                          `send_active` will start a new transmission.
    """

    START_BIT = 0
    STOP_BIT  = 1

    def __init__(self, *, divisor):
        """
        Parameters:
            divisor -- number of `sync` clock cycles per bit period
        """

        self.divisor = divisor

        #
        # I/O port
        #
        self.tx              = Signal(reset=1)

        self.send            = Signal()
        self.data            = Signal(8)
        self.accepted        = Signal()

        self.idle            = Signal()


    def elaborate(self, platform):
        m = Module()

        # Baud generator.
        baud_counter = Signal(range(0, self.divisor))

        # Tx shift register; holds our data, a start, and a stop bit.
        bits_per_frame = len(self.data) + 2
        data_shift     = Signal(bits_per_frame)
        bits_to_send   = Signal(range(0, len(data_shift)))

        # Create an internal signal equal to our input data framed with a start/stop bit.
        framed_data_in = Cat(self.START_BIT, self.data, self.STOP_BIT)

        # Idle our strobes low unless asserted.
        m.d.sync += [
            self.accepted  .eq(0)
        ]

        with m.FSM() as f:
            m.d.comb += self.idle.eq(f.ongoing('IDLE'))

            # IDLE: transmitter is waiting for input
            with m.State("IDLE"):
                m.d.comb += self.tx.eq(1)  # idle high

                # Once we get a send request, fill in our shift register, and start shifting.
                with m.If(self.send):
                    m.d.sync += [
                        baud_counter  .eq(self.divisor   - 1),
                        bits_to_send  .eq(len(data_shift) - 1),
                        data_shift    .eq(framed_data_in),
                        self.accepted .eq(1)
                    ]

                    m.next = "TRANSMIT"


            # TRANSMIT: actively shift out start/data/stop
            with m.State("TRANSMIT"):
                m.d.comb += self.tx       .eq(data_shift[0])
                m.d.sync += baud_counter  .eq(baud_counter - 1)

                # If we've finished a bit period...
                with m.If(baud_counter == 0):
                    m.d.sync += baud_counter.eq(self.divisor - 1)

                    # ... if we have bits left to send, move to the next one.
                    with m.If(bits_to_send > 0):
                        m.d.sync += [
                            bits_to_send .eq(bits_to_send - 1),
                            data_shift   .eq(data_shift[1:])
                        ]

                    # Otherwise, complete the frame.
                    with m.Else():

                        # If we still have data to send, move to the next byte...
                        with m.If(self.send):
                            m.d.sync += [
                                bits_to_send  .eq(bits_per_frame - 1),
                                data_shift    .eq(framed_data_in),
                                self.accepted .eq(1)
                            ]

                        # ... otherwise, move to our idle state.
                        with m.Else():
                            m.next = "IDLE"


        return m


class UARTTransmitterTest(LunaGatewareTestCase):
    DIVISOR = 10

    FRAGMENT_UNDER_TEST = UARTTransmitter
    FRAGMENT_ARGUMENTS = dict(divisor=DIVISOR)


    def advance_half_bit(self):
        yield from self.advance_cycles(self.DIVISOR // 2)

    def advance_bit(self):
        yield from self.advance_cycles(self.DIVISOR)


    def assert_data_sent(self, byte_expected):
        dut = self.dut

        # Our start bit should remain present until the next bit period.
        yield from self.advance_half_bit()
        self.assertEqual((yield dut.tx), 0)

        # We should then see each bit of our data, LSB first.
        bits = [int(i) for i in f"{byte_expected:08b}"]
        for bit in bits[::-1]:
            yield from self.advance_bit()
            self.assertEqual((yield dut.tx), bit)

        # Finally, we should see a stop bit.
        yield from self.advance_bit()
        self.assertEqual((yield dut.tx), 1)


    @sync_test_case
    def test_burst_transmit(self):
        dut = self.dut

        # We should remain idle until a transmit is requested...
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.idle), 1)
        self.assertEqual((yield dut.accepted), 0)

        # ... and our tx line should idle high.
        self.assertEqual((yield dut.tx), 1)

        # First, transmit 0x55 (maximum transition rate).
        yield dut.data.eq(0x55)
        yield dut.send.eq(1)

        # We should see our data become accepted; and we
        # should see a start bit.
        yield from self.advance_cycles(2)
        self.assertEqual((yield dut.accepted), 1)
        self.assertEqual((yield dut.tx), 0)

        # Provide our next byte of data once the current
        # one has been accepted. Changing this before the tests
        # below ensures that we validate that data is latched properly.
        yield dut.data.eq(0x66)

        # Ensure we get our data correctly.
        yield from self.assert_data_sent(0x55)
        yield from self.assert_data_sent(0x66)

        # Stop transmitting after the next frame.
        yield dut.send.eq(0)

        # Ensure we actually stop.
        yield from self.advance_bit()
        self.assertEqual((yield dut.idle), 1)




if __name__ == "__main__":
    unittest.main()
