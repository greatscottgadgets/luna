#
# This file is part of LUNA.
#
""" Stream generators. """

import unittest

from nmigen import Elaboratable, Signal, Module, DomainRenamer, Memory, Array
from .      import StreamInterface
from ..test import LunaGatewareTestCase, sync_test_case, usb_domain_test_case


class ConstantStreamGenerator(Elaboratable):
    """ Gateware that generates stream of constant data.

    I/O port:
        I: start        -- Strobe that indicates when the stream should be started.
        O: done         -- Strobe that pulses high when we're finishing a transmission.

        I: max_length[] -- The maximum length to be sent. Defaults to the length of the stream.
                           Only present if the `max_length_width` parameter is provided on creation.

        *: stream       -- The generated stream interface.

    """


    def __init__(self, constant_data, domain="sync", data_width=8, stream_type=StreamInterface, max_length_width=None):
        """
        Parameters:
            constant_data      -- The constant data for the stream to be generated.
                                  Should be an array of integers; or, if data_width=8, a bytes-like object.
            domain             -- The clock domain this generator should belong to. Defaults to 'sync'.
            data_width         -- The width of the constant payload
            stream_type        -- The type of stream we'll be multiplexing. Must be a subclass of StreamInterface.
            max_length_width   -- If provided, a `max_length` signal will be present that can limit the total length
                                  transmitted.
        """

        self.domain      = domain
        self.data        = constant_data
        self.data_width  = data_width
        self.data_length = len(constant_data)

        #
        # I/O port.
        #
        self.start      = Signal()
        self.done       = Signal()
        self.stream     = stream_type(payload_width=data_width)

        # If we have a maximum length width, include it in our I/O port.
        # Otherwise, use a constant.
        if max_length_width:
            self.max_length = Signal(max_length_width)
        else:
            self.max_length = self.data_length



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

        # Track when we're on the first and last packet.
        on_first_packet = position_in_stream == 0
        on_last_packet  = \
            (position_in_stream == (data_length - 1))      | \
            (position_in_stream == (self.max_length - 1))

        m.d.comb += [
            # Always drive the stream from our current memory output...
            self.stream.payload  .eq(rom_read_port.data),

            ## ... and base First and Last based on our current position in the stream.
            self.stream.first    .eq(on_first_packet & self.stream.valid),
            self.stream.last     .eq(on_last_packet  & self.stream.valid)
        ]



        #
        # Controller.
        #
        with m.FSM(domain=self.domain) as fsm:
            m.d.comb += self.stream.valid.eq(fsm.ongoing('STREAMING'))

            # IDLE -- we're not actively transmitting.
            with m.State('IDLE'):

                # Keep ourselves at the beginning of the stream, but don't yet count.
                m.d.sync += position_in_stream.eq(0)

                # Once the user requests that we start, move to our stream being valid.
                with m.If(self.start & (self.max_length > 0)):
                    m.next = 'STREAMING'


            # STREAMING -- we're actively transmitting data
            with m.State('STREAMING'):
                m.d.comb += [
                    rom_read_port.addr  .eq(position_in_stream)
                ]

                # If the current data byte is accepted, move past it.
                with m.If(self.stream.ready):

                    should_continue = \
                        ((position_in_stream + 1) < self.max_length) & \
                        ((position_in_stream + 1) < data_length)

                    # If there's still data left to transmit, move forward.
                    with m.If(should_continue):
                        m.d.sync += position_in_stream.eq(position_in_stream + 1)
                        m.d.comb += rom_read_port.addr.eq(position_in_stream + 1)

                    # Otherwise, we've finished streaming. Return to IDLE.
                    with m.Else():
                        m.next = 'DONE'

            # DONE -- report our completion; and then return to idle
            with m.State('DONE'):
                m.d.comb += self.done.eq(1)
                m.next = 'IDLE'


        # Convert our sync domain to the domain requested by the user, if necessary.
        if self.domain != "sync":
            m = DomainRenamer({"sync": self.domain})(m)

        return m


class ConstantStreamGeneratorTest(LunaGatewareTestCase):
    FRAGMENT_UNDER_TEST = ConstantStreamGenerator
    FRAGMENT_ARGUMENTS  = {'constant_data': b"HELLO, WORLD", 'domain': "usb"}

    # Run our test in the USB domain, to test domain translation.
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY  = 60e6


    @usb_domain_test_case
    def test_basic_transmission(self):
        dut = self.dut

        # We shouldn't see a transmission before we request a start.
        yield from self.advance_cycles(10)
        self.assertEqual((yield dut.stream.valid), 0)
        self.assertEqual((yield dut.stream.first), 0)
        self.assertEqual((yield dut.stream.last),  0)

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


    @usb_domain_test_case
    def test_max_length(self):
        dut = self.dut

        yield dut.stream.ready.eq(1)
        yield dut.max_length.eq(6)

        # Once we pulse start, we should see the transmission start,
        yield from self.pulse(dut.start)

        # ... we should start seeing the remainder of our transmission.
        for i in 'HELLO':
            self.assertEqual((yield dut.stream.payload), ord(i))
            yield


        # On the last byte of data, we should see last = 1.
        self.assertEqual((yield dut.stream.last),   1)

        # After the last datum, we should see valid drop to '0'.
        yield
        self.assertEqual((yield dut.stream.valid), 0)



class StreamSerializer(Elaboratable):
    """ Gateware that serializes a short Array input onto a stream.

    I/O port:
        I: start        -- Strobe that indicates when the stream should be started.
        O: done         -- Strobe that pulses high when we're finishing a transmission.

        I: data[]       -- The data stream to be sent out. Length is set by the data_length initializer argument.
        I: max_length[] -- The maximum length to be sent. Defaults to the length of the stream.
                           Only present if the `max_length_width` parameter is provided on creation.

        *: stream       -- The generated stream interface.

    """

    def __init__(self, data_length, domain="sync", data_width=8, stream_type=StreamInterface, max_length_width=None):
        """
        Parameters:
            constant_data      -- The constant data for the stream to be generated.
                                  Should be an array of integers; or, if data_width=8, a bytes-like object.
            domain             -- The clock domain this generator should belong to. Defaults to 'sync'.
            data_width         -- The width of the constant payload
            stream_type        -- The type of stream we'll be multiplexing. Must be a subclass of StreamInterface.
            max_length_width   -- If provided, a `max_length` signal will be present that can limit the total length
                                  transmitted.
        """

        self.domain      = domain
        self.data_width  = data_width
        self.data_length = data_length

        #
        # I/O port.
        #
        self.start       = Signal()
        self.done        = Signal()

        self.data        = Array(Signal(data_width, name=f"datum_{i}") for i in range(data_length))
        self.stream      = stream_type(payload_width=data_width)


        # If we have a maximum length width, include it in our I/O port.
        # Otherwise, use a constant.
        if max_length_width:
            self.max_length = Signal(max_length_width)
        else:
            self.max_length = self.data_length



    def elaborate(self, platform):
        m = Module()

        # Register that stores our current position in the stream.
        position_in_stream = Signal(range(0, self.data_length))

        # Track when we're on the first and last packet.
        on_first_packet = position_in_stream == 0
        on_last_packet  = \
            (position_in_stream == (self.data_length - 1)) | \
            (position_in_stream == (self.max_length - 1))

        m.d.comb += [
            # Create first and last based on our stream position.
            self.stream.first    .eq(on_first_packet & self.stream.valid),
            self.stream.last     .eq(on_last_packet  & self.stream.valid)
        ]


        #
        # Controller.
        #
        with m.FSM(domain=self.domain) as fsm:
            m.d.comb += self.stream.valid.eq(fsm.ongoing('STREAMING'))

            # IDLE -- we're not actively transmitting.
            with m.State('IDLE'):

                # Keep ourselves at the beginning of the stream, but don't yet count.
                m.d.sync += position_in_stream.eq(0)

                # Once the user requests that we start, move to our stream being valid.
                with m.If(self.start & (self.max_length > 0)):
                    m.next = 'STREAMING'


            # STREAMING -- we're actively transmitting data
            with m.State('STREAMING'):
                m.d.comb += self.stream.payload.eq(self.data[position_in_stream])

                # If the current data byte is accepted, move past it.
                with m.If(self.stream.ready):

                    should_continue = \
                        ((position_in_stream + 1) < self.max_length) & \
                        ((position_in_stream + 1) < self.data_length)

                    # If there's still data left to transmit, move forward.
                    with m.If(should_continue):
                        m.d.sync += position_in_stream.eq(position_in_stream + 1)
                        m.d.comb += self.stream.payload.eq(self.data[position_in_stream + 1])

                    # Otherwise, we've finished streaming. Return to IDLE.
                    with m.Else():
                        m.next = 'DONE'

            # DONE -- report our completion; and then return to idle
            with m.State('DONE'):
                m.d.comb += self.done.eq(1)
                m.next = 'IDLE'


        # Convert our sync domain to the domain requested by the user, if necessary.
        if self.domain != "sync":
            m = DomainRenamer({"sync": self.domain})(m)

        return m


if __name__ == "__main__":
    unittest.main()
