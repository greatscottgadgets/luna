#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" UART interface gateware."""

import unittest

from amaranth   import Elaboratable, Module, Signal, Cat
from amaranth_soc import wishbone, memory


from ..stream       import StreamInterface
from ..test         import LunaGatewareTestCase, sync_test_case


class UARTTransmitter(Elaboratable):
    """ Simple UART transitter.

    Intended for communicating with the debug controller; currently assumes 8n1.

    Attributes
    ----------

    tx: Signal(), output
        The UART output.
    driving: Signal(), output
        True iff the UART is in the middle of driving data. In some cases, it's desireable
        to have the UART drive the line only when it is actively sending; letting a pull
        resistor handle pulling the line to idle. This line can be used to determine when the
        line should be driven.

    stream: input stream
        The stream carrying the data to be sent.

    idle: Signal(), output
        Asserted when the transmitter is idle; and thus pulsing `send_active`
        will start a new transmission.

    Parameters
    ------------
    divisor: int
        The number of `sync` clock cycles per bit period.
    """

    START_BIT = 0
    STOP_BIT  = 1

    def __init__(self, *, divisor):
        self.divisor = divisor

        #
        # I/O port
        #
        self.tx              = Signal(reset=1)
        self.driving         = Signal()
        self.stream          = StreamInterface()

        self.idle            = Signal()


    def elaborate(self, platform):
        m = Module()

        # Baud generator.
        baud_counter = Signal(range(0, self.divisor))

        # Tx shift register; holds our data, a start, and a stop bit.
        bits_per_frame = len(self.stream.payload) + 2
        data_shift     = Signal(bits_per_frame)
        bits_to_send   = Signal(range(0, len(data_shift)))

        # Create an internal signal equal to our input data framed with a start/stop bit.
        framed_data_in = Cat(self.START_BIT, self.stream.payload, self.STOP_BIT)


        with m.FSM() as f:
            m.d.comb += self.idle.eq(f.ongoing('IDLE'))

            # IDLE: transmitter is waiting for input
            with m.State("IDLE"):
                m.d.comb += [
                    self.tx            .eq(1),
                    self.stream.ready  .eq(1)
                ]


                # Once we get a send request, fill in our shift register, and start shifting.
                with m.If(self.stream.valid):
                    m.d.sync += [
                        baud_counter      .eq(self.divisor   - 1),
                        bits_to_send      .eq(len(data_shift) - 1),
                        data_shift        .eq(framed_data_in),
                    ]

                    m.next = "TRANSMIT"


            # TRANSMIT: actively shift out start/data/stop
            with m.State("TRANSMIT"):
                m.d.sync += baud_counter  .eq(baud_counter - 1)
                m.d.comb += [
                    self.tx       .eq(data_shift[0]),
                    self.driving  .eq(1)
                ]

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
                        m.d.comb += self.stream.ready.eq(1)

                        # If we still have data to send, move to the next byte...
                        with m.If(self.stream.valid):
                            m.d.sync += [
                                bits_to_send  .eq(bits_per_frame - 1),
                                data_shift    .eq(framed_data_in),
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
        stream = dut.stream

        # We should remain idle until a transmit is requested...
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.idle), 1)
        self.assertEqual((yield dut.stream.ready), 1)

        # ... and our tx line should idle high.
        self.assertEqual((yield dut.tx), 1)

        # First, transmit 0x55 (maximum transition rate).
        yield stream.payload.eq(0x55)
        yield stream.valid.eq(1)

        # We should see our data become accepted; and we
        # should see a start bit.
        yield
        self.assertEqual((yield stream.ready), 1)
        yield
        self.assertEqual((yield dut.tx), 0)

        # Provide our next byte of data once the current
        # one has been accepted. Changing this before the tests
        # below ensures that we validate that data is latched properly.
        yield stream.payload.eq(0x66)

        # Ensure we get our data correctly.
        yield from self.assert_data_sent(0x55)
        yield from self.assert_data_sent(0x66)

        # Stop transmitting after the next frame.
        yield stream.valid.eq(0)

        # Ensure we actually stop.
        yield from self.advance_bit()
        self.assertEqual((yield dut.idle), 1)


class UARTTransmitterPeripheral(Elaboratable):
    """ Wishbone-attached variant of our UARTTransmitter.

    Attributes
    ----------
    tx: Signal(), output
        The UART line to use for transmission.
    bus: wishbone bus
        Wishbone interface used for UART connections.

    Parameters
    ----------
    divisor: int
        number of `sync` clock cycles per bit period
    """

    # TODO: include a variant of misoc/LiteX's autoregister mechanism

    def __init__(self, divisor):
        self.divisor = divisor

        #
        # I/O port
        #
        self.tx  = Signal()
        self.bus = wishbone.Interface(addr_width=0, data_width=8)
        self.bus.memory_map = memory.MemoryMap(addr_width=1, data_width=8)


    def elaborate(self, platform):
        m = Module()

        # Create our UART transmitter, and connect it directly to our
        # wishbone bus.
        m.submodules.tx = tx = UARTTransmitter(divisor=self.divisor)
        m.d.comb += [
            tx.stream.valid    .eq(self.bus.cyc & self.bus.stb & self.bus.we),
            tx.stream.payload  .eq(self.bus.dat_w),

            self.bus.ack.eq(tx.stream.ready),
            self.tx.eq(tx.tx)
        ]
        return m


class UARTMultibyteTransmitter(Elaboratable):
    """ UART transmitter capable of sending wide words.

    Intended for communicating with the debug controller; currently assumes 8n1.
    Transmits our words little-endian.

    Attributes
    ----------

    tx: Signal(), output
        The UART output.
    stream: input stream
        The data to be transmitted.

    accepted: Signal(), output
        Strobe that indicates when the `data` word has been latched in;
        and the next data byte can be presented.
    idle: Signal(), output
        Asserted when the transmitter is idle; and thus pulsing `send_active`
        will start a new transmission.

    Parameters
    ------------
    byte_width: int
        The number of bytes to be accepted at once.

    divisor: int
        The number of `sync` clock cycles per bit period.
    """
    def __init__(self, *, byte_width, divisor):
        self.byte_width = byte_width
        self.divisor = divisor

        #
        # I/O port
        #
        self.tx              = Signal(reset=1)
        self.stream          = StreamInterface(payload_width=byte_width * 8)

        self.idle            = Signal()


    def elaborate(self, platform):
        m = Module()

        # Create our core UART transmitter.
        m.submodules.uart = uart = UARTTransmitter(divisor=self.divisor)

        # We'll put each word to be sent through an shift register
        # that shifts out words a byte at a time.
        data_shift = Signal.like(self.stream.payload)

        # Count how many bytes we have left to send.
        bytes_to_send = Signal(range(0, self.byte_width + 1))

        m.d.comb += [

            # Connect our transmit output directly through.
            self.tx.eq(uart.tx),

            # Always provide our UART with the least byte of our shift register.
            uart.stream.payload.eq(data_shift[0:8])
        ]



        with m.FSM() as f:
            m.d.comb += self.idle.eq(f.ongoing('IDLE'))

            # IDLE: transmitter is waiting for input
            with m.State("IDLE"):
                m.d.comb += self.stream.ready.eq(1)

                # Once we get a send request, fill in our shift register, and start shifting.
                with m.If(self.stream.valid):
                    m.d.sync += [
                        data_shift         .eq(self.stream.payload),
                        bytes_to_send      .eq(self.byte_width - 1),
                    ]
                    m.next = "TRANSMIT"


            # TRANSMIT: actively send each of the bytes of our word
            with m.State("TRANSMIT"):
                m.d.comb += uart.stream.valid.eq(1)

                # Once the UART is accepting our input...
                with m.If(uart.stream.ready):

                    # ... if we have bytes left to send, move to the next one.
                    with m.If(bytes_to_send > 0):
                        m.d.sync += [
                            bytes_to_send .eq(bytes_to_send - 1),
                            data_shift    .eq(data_shift[8:]),
                        ]

                    # Otherwise, complete the frame.
                    with m.Else():
                        m.d.comb += self.stream.ready.eq(1)

                        # If we still have data to send, move to the next byte...
                        with m.If(self.stream.valid):
                            m.d.sync += [
                                bytes_to_send      .eq(self.byte_width - 1),
                                data_shift         .eq(self.stream.payload),
                            ]

                        # ... otherwise, move to our idle state.
                        with m.Else():
                            m.next = "IDLE"


        return m


class UARTMultibyteTransmitterTest(LunaGatewareTestCase):
    DIVISOR = 10

    FRAGMENT_UNDER_TEST = UARTMultibyteTransmitter
    FRAGMENT_ARGUMENTS = dict(divisor=DIVISOR, byte_width=4)


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

        yield from self.advance_cycles(2)


    @sync_test_case
    def test_burst_transmit(self):
        dut = self.dut
        stream = dut.stream

        # We should remain idle until a transmit is requested...
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.idle), 1)
        self.assertEqual((yield dut.stream.ready), 1)

        # Transmit a four-byte word.
        yield stream.payload.eq(0x11223355)
        yield stream.valid.eq(1)

        # We should see our data become accepted; and we
        # should see a start bit.
        yield
        self.assertEqual((yield stream.ready), 1)

        # Ensure we get our data correctly, and that our transmitter
        # isn't accepting data mid-frame.
        yield from self.assert_data_sent(0x55)
        self.assertEqual((yield stream.ready), 0)
        yield from self.assert_data_sent(0x33)



if __name__ == "__main__":
    unittest.main()
