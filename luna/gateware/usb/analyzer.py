#
# This file is part of LUNA.
#
""" Low-level USB analyzer gateware. """


import unittest

from nmigen            import Signal, Module, Elaboratable, Memory, Record
from nmigen.back.pysim import Simulator

from ..test           import LunaGatewareTestCase, ulpi_domain_test_case, sync_test_case


class USBAnalyzer(Elaboratable):
    """ Core USB analyzer; backed by a small ringbuffer in FPGA block RAM.

    If you're looking to instantiate a full analyzer, you'll probably want to grab
    one of the DRAM-based ringbuffer variants (which are currently forthcoming).

    If you're looking to use this with a ULPI PHY, rather than the FPGA-convenient UTMI interface,
    grab the UTMITranslator from `luna.gateware.interface.ulpi`.

    I/O port:
        O: data_available -- indicates that new data is available in the analysis stream
        O: data_out[8]    -- the next byte in the captured stream; valid when data_available is asserted
        I: next           -- strobe that indicates when the data_out byte has been accepted; and can be
                             discarded from the local memory
    """

    # Current, we'll provide a packet header of 16 bits.
    HEADER_SIZE_BITS = 16
    HEADER_SIZE_BYTES = HEADER_SIZE_BITS // 8

    # Support a maximum payload size of 1024B, plus a 1-byte PID and a 2-byte CRC16.
    MAX_PACKET_SIZE_BYTES = 1024 + 1 + 2

    def __init__(self, *, utmi_interface, mem_depth=8192):
        """
        Parameters:
            utmi_interface -- A record or elaboratable that presents a UTMI interface.
        """

        self.utmi = utmi_interface

        # Internal storage memory.
        self.mem = Memory(width=8, depth=mem_depth, name="analysis_ringbuffer")
        self.mem_size = mem_depth

        #
        # I/O port
        #
        self.data_available = Signal()
        self.data_out       = Signal(8)
        self.next           = Signal()


        self.overrun        = Signal()
        self.capturing      = Signal()

        # Diagnostic I/O.
        self.sampling       = Signal()


    def elaborate(self, platform):
        m = Module()

        # Memory read and write ports.
        m.submodules.read  = mem_read_port  = self.mem.read_port(domain="ulpi")
        m.submodules.write = mem_write_port = self.mem.write_port(domain="ulpi")

        # Store the memory address of our active packet header, which will store
        # packet metadata like the packet size.
        header_location = Signal.like(mem_write_port.addr)
        write_location  = Signal.like(mem_write_port.addr)

        # Read FIFO status.
        read_location   = Signal.like(mem_read_port.addr)
        fifo_count      = Signal.like(mem_read_port.addr, reset=0)
        fifo_new_data   = Signal()

        # Current receive status.
        packet_size     = Signal(16)

        #
        # Read FIFO logic.
        #
        m.d.comb += [

            # We have data ready whenever there's not data in the FIFO.
            self.data_available .eq(fifo_count != 0),

            # Our data_out is always the output of our read port...
            self.data_out       .eq(mem_read_port.data),

            # ... and our read port always reads from our read pointer.
            mem_read_port.addr  .eq(read_location),


            self.sampling       .eq(mem_write_port.en)
        ]

        # Once our consumer has accepted our current data, move to the next address.
        with m.If(self.next & self.data_available):
            m.d.ulpi += read_location.eq(read_location + 1)


        #
        # FIFO count handling.
        #
        fifo_full = (fifo_count == self.mem_size)

        data_pop   = Signal()
        data_push  = Signal()
        m.d.comb += [
            data_pop   .eq(self.next & self.data_available),
            data_push  .eq(fifo_new_data & ~fifo_full)
        ]

        # If we have both a read and a write, don't update the count,
        # as we've both added one and subtracted one.
        with m.If(data_push & data_pop):
            pass

        # Otherwise, add when data's added, and subtract when data's removed.
        with m.Elif(data_push):
            m.d.ulpi += fifo_count.eq(fifo_count + 1)
        with m.Elif(data_pop):
            m.d.ulpi += fifo_count.eq(fifo_count - 1)


        #
        # Core analysis FSM.
        #
        with m.FSM(domain="ulpi") as f:
            m.d.comb += [
                self.overrun   .eq(f.ongoing("OVERRUN")),
                self.capturing .eq(f.ongoing("CAPTURE")),
            ]

            # IDLE: wait for an active receive.
            with m.State("IDLE"):

                # Wait until a transmission is active.
                # TODO: add triggering logic?
                with m.If(self.utmi.rx_active):
                    m.next = "CAPTURE"
                    m.d.ulpi += [
                        header_location  .eq(write_location),
                        write_location   .eq(write_location + self.HEADER_SIZE_BYTES),
                        packet_size      .eq(0),
                    ]


            # Capture data until the packet is complete.
            with m.State("CAPTURE"):

                # Capture data whenever RxValid is asserted.
                m.d.comb += [
                    mem_write_port.addr  .eq(write_location),
                    mem_write_port.data  .eq(self.utmi.rx_data),
                    mem_write_port.en    .eq(self.utmi.rx_valid & self.utmi.rx_active),
                    fifo_new_data        .eq(self.utmi.rx_valid & self.utmi.rx_active)
                ]

                # Advance the write pointer each time we receive a bit.
                with m.If(self.utmi.rx_valid & self.utmi.rx_active):
                    m.d.ulpi += [
                        write_location  .eq(write_location + 1),
                        packet_size     .eq(packet_size + 1)
                    ]

                    # If this would be filling up our data memory,
                    # move to the OVERRUN state.
                    with m.If(fifo_count == self.mem_size - 1 - self.HEADER_SIZE_BYTES):
                        m.next = "OVERRUN"

                # If we've stopped receiving, move to the "finalize" state.
                with m.If(~self.utmi.rx_active):

                    # Optimization: if we didn't receive any data, there's no need
                    # to create a packet. Clear our header from the FIFO and disarm.
                    with m.If(packet_size == 0):
                        m.next = "IDLE"
                        m.d.ulpi += [
                            write_location.eq(header_location)
                        ]
                    with m.Else():
                        m.next = "EOP_1"

            # EOP: handle the end of the relevant packet.
            with m.State("EOP_1"):

                # Now that we're done, add the header to the start of our packet.
                # This will take two cycles, currently, as we're using a 2-byte header,
                # but we only have an 8-bit write port.
                m.d.comb += [
                    mem_write_port.addr  .eq(header_location),
                    mem_write_port.data  .eq(packet_size[7:16]),
                    #mem_write_port.data  .eq(0xAA),
                    mem_write_port.en    .eq(1),
                    fifo_new_data        .eq(1)
                ]
                m.next = "EOP_2"


            with m.State("EOP_2"):

                # Add the second byte of our header.
                # Note that, if this is an adjacent read, we should have
                # just captured our packet header _during_ the stop turnaround.
                m.d.comb += [
                    mem_write_port.addr  .eq(header_location + 1),
                    mem_write_port.data  .eq(packet_size[0:8]),
                    mem_write_port.en    .eq(1),
                    fifo_new_data        .eq(1)
                ]


                # Move to the next state, which will either be another capture,
                # or our idle state, depending on whether we have another rx.
                with m.If(self.utmi.rx_active):
                    m.next = "CAPTURE"
                    m.d.ulpi += [
                        header_location  .eq(write_location),
                        write_location   .eq(write_location + self.HEADER_SIZE_BYTES),
                        packet_size      .eq(0),
                    ]

                    # FIXME: capture if rx_valid

                with m.Else():
                    m.next = "IDLE"


            # BABBLE -- handles the case in which we've received a packet beyond
            # the allowable size in the USB spec
            with m.State("BABBLE"):

                # Trap here, for now.
                pass


            with m.State("OVERRUN"):
                # TODO: we should probably set an overrun flag and then emit an EOP, here?

                pass


        return m



class USBAnalyzerTest(LunaGatewareTestCase):

    SYNC_CLOCK_FREQUENCY = None
    ULPI_CLOCK_FREQUENCY = 60e6

    def instantiate_dut(self):
        self.utmi = Record([
            ('tx_data',     8),
            ('rx_data',    8),

            ('rx_valid',    1),
            ('rx_active',   1),
            ('rx_error',    1),
            ('rx_complete', 1),
        ])
        return USBAnalyzer(utmi_interface=self.utmi, mem_depth=128)


    def advance_stream(self, value):
        yield self.utmi.rx_data.eq(value)
        yield


    @ulpi_domain_test_case
    def test_single_packet(self):

        # Ensure we're not capturing until a transaction starts.
        self.assertEqual((yield self.dut.capturing), 0)

        # Apply our first input, and validate that we start capturing.
        yield self.utmi.rx_active.eq(1)
        yield self.utmi.rx_valid.eq(1)
        yield self.utmi.rx_data.eq(0)
        yield
        yield

        # Provide some data.
        for i in range(1, 10):
            yield from self.advance_stream(i)
            self.assertEqual((yield self.dut.capturing), 1)

        # Ensure we're still capturing, _and_ that we have
        # data available.
        self.assertEqual((yield self.dut.capturing), 1)
        self.assertEqual((yield self.dut.data_available), 1)

        # End our packet.
        yield self.utmi.rx_active.eq(0)
        yield from self.advance_stream(10)

        # Idle for several cycles.
        yield from self.advance_cycles(5)
        self.assertEqual((yield self.dut.capturing), 0)

        # Try to read back the capture data, byte by byte.
        self.assertEqual((yield self.dut.data_available), 1)

        # First, we should get a header with the total data length.
        # This should be 0x00, 0x0B; as we captured 11 bytes.
        self.assertEqual((yield self.dut.data_out), 0)
        yield self.dut.next.eq(1)
        yield from self.advance_cycles(2)

        # Validate that we get all of the bytes of the packet we expected.
        expected_data = [0x00, 0x0a] + list(range(0, 10))
        for datum in expected_data:
            self.assertEqual((yield self.dut.data_out), datum)
            yield

        # We should now be out of data -- verify that there's no longer data available.
        self.assertEqual((yield self.dut.data_available), 0)


    @ulpi_domain_test_case
    def test_short_packet(self):

        # Apply our first input, and validate that we start capturing.
        yield self.utmi.rx_active.eq(1)
        yield self.utmi.rx_valid.eq(1)
        yield self.utmi.rx_data.eq(0)
        yield

        # Provide some data.
        yield from self.advance_stream(0xAB)

        # End our packet.
        yield self.utmi.rx_active.eq(0)
        yield from self.advance_stream(10)

        # Idle for several cycles.
        yield from self.advance_cycles(5)
        self.assertEqual((yield self.dut.capturing), 0)

        # Try to read back the capture data, byte by byte.
        self.assertEqual((yield self.dut.data_available), 1)

        # First, we should get a header with the total data length.
        # This should be 0x00, 0x01; as we captured 1 byte.
        self.assertEqual((yield self.dut.data_out), 0)
        yield self.dut.next.eq(1)
        yield from self.advance_cycles(2)

        # Validate that we get all of the bytes of the packet we expected.
        expected_data = [0x00, 0x01, 0xab]
        for datum in expected_data:
            self.assertEqual((yield self.dut.data_out), datum)
            yield

        # We should now be out of data -- verify that there's no longer data available.
        self.assertEqual((yield self.dut.data_available), 0)


    @ulpi_domain_test_case
    def test_rx_valid_low(self):

        # Apply our first input, and validate that we start capturing.
        yield self.utmi.rx_active.eq(1)
        yield self.utmi.rx_valid.eq(1)
        yield self.utmi.rx_data.eq(0)
        yield

        # Provide some data.
        yield from self.advance_stream(0xAB)

        # Provide a byte that shouldn't be counted.
        yield self.utmi.rx_valid.eq(0)
        yield from self.advance_stream(0xCD)

        # ... and another that should be.
        yield self.utmi.rx_valid.eq(1)
        yield from self.advance_stream(0xEF)

        # End our packet.
        yield self.utmi.rx_active.eq(0)
        yield from self.advance_stream(10)

        # Idle for several cycles.
        yield from self.advance_cycles(5)
        self.assertEqual((yield self.dut.capturing), 0)

        # Try to read back the capture data, byte by byte.
        self.assertEqual((yield self.dut.data_available), 1)

        # First, we should get a header with the total data length.
        # This should be 0x00, 0x01; as we captured 1 byte.
        self.assertEqual((yield self.dut.data_out), 0)
        yield self.dut.next.eq(1)
        yield from self.advance_cycles(2)

        # Validate that we get all of the bytes of the packet we expected.
        expected_data = [0x00, 0x02, 0xab, 0xef]
        for datum in expected_data:
            self.assertEqual((yield self.dut.data_out), datum)
            yield

        # We should now be out of data -- verify that there's no longer data available.
        self.assertEqual((yield self.dut.data_available), 0)


    @ulpi_domain_test_case
    def test_multi_packet_with_overflow(self):

        yield self.utmi.rx_active.eq(1)
        yield self.utmi.rx_valid.eq(0)

        yield
        yield self.utmi.rx_valid.eq(1)

        # Provide some data.
        for i in range(0, 10):
            yield from self.advance_stream(0x10 + i)

        # End our packet.
        yield self.utmi.rx_active.eq(0)
        yield from self.advance_stream(10)

        # Idle for several cycles.
        yield from self.advance_cycles(5)
        self.assertEqual((yield self.dut.capturing), 0)

        # Start our second packet.
        yield self.utmi.rx_active.eq(1)
        yield self.utmi.rx_valid.eq(1)
        yield

        # Provide some data.
        for i in range(0, 4):
            yield from self.advance_stream(0x30 + i)

        # End our packet.
        yield self.utmi.rx_active.eq(0)
        yield from self.advance_stream(10)

        # Idle for several cycles.
        yield from self.advance_cycles(5)
        self.assertEqual((yield self.dut.capturing), 0)

        # Start a third packet; which should cause an overflow.
        yield self.utmi.rx_active.eq(1)
        yield self.utmi.rx_valid.eq(1)

        # Provide some data, and keep going until we overflow.
        for i in range(0, 110):
            yield from self.advance_stream(0x0 + i)


        # Validate that we can read out the packet data we're expecting.
        yield self.dut.next.eq(1)
        yield
        yield

        expected_data = \
           [0x00, 10] + [i + 0x10 for i in range(0, 10)] + \
           [0x00,  4] + [i + 0x30 for i in range(0,  4)]
        for index, datum in enumerate(expected_data):
            self.assertEqual((yield self.dut.data_out), datum, f"item {index}")
            yield



class USBAnalyzerStackTest(LunaGatewareTestCase):
    """ Test that evaluates a full-stack USB analyzer setup. """

    SYNC_CLOCK_FREQUENCY = None
    ULPI_CLOCK_FREQUENCY = 60e6


    def instantiate_dut(self):

        from ..interface.ulpi import UTMITranslator

        self.ulpi = Record([
            ('data', [
                ('i',  8),
                ('o',  8),
                ('oe', 8),
            ]),
            ('nxt', 1),
            ('stp', 1),
            ('dir', [('i', 1)]),
            ('clk', 1),
            ('rst', 1)
        ])

        # Create a stack of our UTMITranslator and our USBAnalyzer.
        # We'll wrap the both in a module to establish a synthetic hierarchy.
        m = Module()
        m.submodules.translator = self.translator = UTMITranslator(ulpi=self.ulpi)
        m.submodules.analyzer   = self.analyzer   = USBAnalyzer(utmi_interface=self.translator, mem_depth=128)
        return m


    def initialize_signals(self):

        # Ensure the translator doesn't need to perform any register reads/writes
        # by default, so we can focus on packet Rx.
        yield self.translator.xcvr_select.eq(1)
        yield self.translator.dm_pulldown.eq(1)
        yield self.translator.dp_pulldown.eq(1)
        yield self.translator.use_external_vbus_indicator.eq(0)


    @ulpi_domain_test_case
    def test_simple_analysis(self):
        yield from self.advance_cycles(10)

        # Start a new packet.
        yield self.ulpi.dir.eq(1)
        yield self.ulpi.nxt.eq(1)

        # Bus turnaround packet.
        yield self.ulpi.data.i.eq(0x80)
        yield

        # Provide some data to be captured.
        for i in [0x2d, 0x00, 0x10]:
            yield self.ulpi.data.i.eq(i)
            yield

        # Mark our packet as complete.
        yield self.ulpi.dir.eq(0)
        yield self.ulpi.nxt.eq(0)
        yield

        # Wait for a few cycles, for realism.
        yield from self.advance_cycles(10)

        # Read our data out of the PHY.
        yield self.analyzer.next.eq(1)
        yield
        yield

        # Validate that we got the correct packet out; plus headers.
        for i in [0x00, 0x03, 0x2d, 0x00, 0x10]:
            self.assertEqual((yield self.analyzer.data_out), i)
            yield



if __name__ == "__main__":
    unittest.main()
