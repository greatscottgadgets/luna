#
# This file is part of LUNA.
#
""" Stream generators. """

import unittest

from nmigen import Elaboratable, Signal, Module, DomainRenamer, Memory
from .      import StreamInterface
from ..test import LunaGatewareTestCase, sync_test_case


class ConstantStreamGenerator(Elaboratable):
    """ Gateware that generates stream of constant data.

    I/O port:
        I: start  -- Strobe that indicates when the stream should be started.
        *: stream -- The generated stream interface.
    """


    def __init__(self, constant_data, domain="sync", data_width=8):
        """
        Parameters:
            constant_data -- The constant data for the stream to be generated.
                             Should be an array of integers; or, if data_width=8, a bytes-like object.
        """

        self.domain     = domain
        self.data       = constant_data
        self.data_width = data_width

        #
        # I/O port.
        #
        self.start   = Signal()
        self.stream  = StreamInterface(payload_width=data_width)



    def elaborate(self, platform):
        m = Module()

        #
        # Core ROM.
        #

        data_length = len(self.data)

        rom = Memory(width=self.data_width, depth=data_length, init=self.data)
        m.submodules.rom_read_port = rom_read_port = rom.read_port()

        # Register that stores our current position in the stream.
        position_in_stream = Signal(range(0, data_length))

        m.d.comb += [
            # Always drive the stream from our current memory output...
            self.stream.payload  .eq(rom_read_port.data),

            # ... and base First and Last based on our current position in the stream.
            self.stream.first    .eq(rom_read_port.addr == 0),
            self.stream.last     .eq(rom_read_port.addr == (data_length - 1))
        ]


        #
        # Controller.
        #
        with m.FSM():

            # IDLE -- we're not actively transmitting.
            with m.State('IDLE'):

                # Keep ourselves at the beginning of the stream, but don't yet count.
                m.d.comb += self.stream.valid.eq(0)
                m.d.sync += position_in_stream.eq(0)

                # Once the user requests that we start, move to our stream being valid.
                with m.If(self.start):
                    m.next = 'STREAMING'


            # STREAMING -- we're actively transmitting data
            with m.State('STREAMING'):
                m.d.comb += [
                    self.stream.valid   .eq(1),
                    rom_read_port.addr  .eq(position_in_stream)
                ]

                # If the current data byte is accepted, move past it.
                with m.If(self.stream.ready):

                    # If there's still data left to transmit, move forward.
                    with m.If((position_in_stream + 1) < data_length):
                        m.d.sync += position_in_stream.eq(position_in_stream + 1)
                        m.d.comb += rom_read_port.addr.eq(position_in_stream + 1)

                    # Otherwise, we've finished streaming. Return to IDLE.
                    with m.Else():
                        m.next = 'IDLE'


        # Convert our sync domain to the domain requested by the user, if necessary.
        if self.domain != "sync":
            m = DomainRenamer({"sync": self.domain})(m)

        return m


class ConstantStreamGeneratorTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = ConstantStreamGenerator
    FRAGMENT_ARGUMENTS  = {'constant_data': b"HELLO, WORLD"}


    @sync_test_case
    def test_basic_transmission(self):
        dut = self.dut

        # We shouldn't see a transmission before we request a start.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid), 0)

        # Once we pulse start, we should see the transmission start,
        # and we should see our first byte of data.
        yield from self.pulse(dut.start)
        self.assertEqual((yield dut.stream.valid),   1)
        self.assertEqual((yield dut.stream.payload), ord('H'))
        self.assertEqual((yield dut.stream.first),   1)

        # That data should remain there until we accept it.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid),   1)
        self.assertEqual((yield dut.stream.payload), ord('H'))

        # Once we indicate that we're accepting data...
        yield dut.stream.ready.eq(1)
        yield

        # ... we should start seeing the remainder of our transmission.
        for i in 'ELLO':
            yield
            self.assertEqual((yield dut.stream.payload), ord(i))
            self.assertEqual((yield dut.stream.first),   0)


        # If we drop the 'accepted', we should still see the next byte...
        yield dut.stream.ready.eq(0)
        yield
        self.assertEqual((yield dut.stream.payload), ord(','))

        # ... but that byte shouldn't be accepted, so we should remain there.
        yield
        self.assertEqual((yield dut.stream.payload), ord(','))

        # If we start accepting data again...
        yield dut.stream.ready.eq(1)
        yield

        # ... we should see the remainder of the stream.
        for i in ' WORLD':
            yield
            self.assertEqual((yield dut.stream.payload), ord(i))


        # On the last byte of data, we should see last = 1.
        self.assertEqual((yield dut.stream.last),   1)

        # After the last datum, we should see valid drop to '0'.
        yield
        self.assertEqual((yield dut.stream.valid), 0)



if __name__ == '__main__':
    unittest.main()
