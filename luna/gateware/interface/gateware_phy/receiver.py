# BSD 3-Clause License
#
# Adapted from ValentyUSB.
#
# Copyright (c) 2020, Great Scott Gadgets <ktemkin@greatscottgadgets.com>
# Copyright (c) 2018, Luke Valenty
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

from amaranth          import Elaboratable, Module, Signal, Cat, Const, ClockSignal
from amaranth.lib.fifo import AsyncFIFOBuffered
from amaranth.hdl.ast  import Past
from amaranth.hdl.xfrm import ResetInserter

from ...utils.cdc import synchronize

class RxClockDataRecovery(Elaboratable):
    """RX Clock Data Recovery module.

    RxClockDataRecovery synchronizes the USB differential pair with the FPGAs
    clocks, de-glitches the differential pair, and recovers the incoming clock
    and data.

    Clock Domain
    ------------
    usb_48 : 48MHz

    Input Ports
    -----------
    Input ports are passed in via the constructor.

    usbp_raw : Signal(1)
        Raw USB+ input from the FPGA IOs, no need to synchronize.

    usbn_raw : Signal(1)
        Raw USB- input from the FPGA IOs, no need to synchronize.

    Output Ports
    ------------
    Output ports are data members of the module. All output ports are flopped.
    The line_state_dj/dk/se0/se1 outputs are 1-hot encoded.

    line_state_valid : Signal(1)
        Asserted for one clock when the output line state is ready to be sampled.

    line_state_dj : Signal(1)
        Represents Full Speed J-state on the incoming USB data pair.
        Qualify with line_state_valid.

    line_state_dk : Signal(1)
        Represents Full Speed K-state on the incoming USB data pair.
        Qualify with line_state_valid.

    line_state_se0 : Signal(1)
        Represents SE0 on the incoming USB data pair.
        Qualify with line_state_valid.

    line_state_se1 : Signal(1)
        Represents SE1 on the incoming USB data pair.
        Qualify with line_state_valid.
    """
    def __init__(self, usbp_raw, usbn_raw):
        self._usbp = usbp_raw
        self._usbn = usbn_raw


        self.line_state_valid = Signal()
        self.line_state_dj = Signal()
        self.line_state_dk = Signal()
        self.line_state_se0 = Signal()
        self.line_state_se1 = Signal()



    def elaborate(self, platform):
        m = Module()

        # Synchronize the USB signals at our I/O boundary.
        # Despite the assumptions made in ValentyUSB, this line rate recovery FSM
        # isn't enough to properly synchronize these inputs. We'll explicitly synchronize.
        sync_dp = synchronize(m, self._usbp, o_domain="usb_io")
        sync_dn = synchronize(m, self._usbn, o_domain="usb_io")

        #######################################################################
        # Line State Recovery State Machine
        #
        # The receive path doesn't use a differential receiver.  Because of
        # this there is a chance that one of the differential pairs will appear
        # to have changed to the new state while the other is still in the old
        # state.  The following state machine detects transitions and waits an
        # extra sampling clock before decoding the state on the differential
        # pair.  This transition period  will only ever last for one clock as
        # long as there is no noise on the line.  If there is enough noise on
        # the line then the data may be corrupted and the packet will fail the
        # data integrity checks.
        #
        dpair =  Cat(sync_dp, sync_dn)

        # output signals for use by the clock recovery stage
        line_state_in_transition = Signal()

        with m.FSM(domain="usb_io") as fsm:
            m.d.usb_io += [
                self.line_state_se0  .eq(fsm.ongoing("SE0")),
                self.line_state_se1  .eq(fsm.ongoing("SE1")),
                self.line_state_dj   .eq(fsm.ongoing("DJ" )),
                self.line_state_dk   .eq(fsm.ongoing("DK" )),
            ]

            # If we are in a transition state, then we can sample the pair and
            # move to the next corresponding line state.
            with m.State("DT"):
                m.d.comb += line_state_in_transition.eq(1)

                with m.Switch(dpair):
                    with m.Case(0b10):
                        m.next = "DJ"
                    with m.Case(0b01):
                        m.next = "DK"
                    with m.Case(0b00):
                        m.next = "SE0"
                    with m.Case(0b11):
                        m.next = "SE1"

            # If we are in a valid line state and the value of the pair changes,
            # then we need to move to the transition state.
            with m.State("DJ"):
                with m.If(dpair != 0b10):
                    m.next = "DT"

            with m.State("DK"):
                with m.If(dpair != 0b01):
                    m.next = "DT"

            with m.State("SE0"):
                with m.If(dpair != 0b00):
                    m.next = "DT"

            with m.State("SE1"):
                with m.If(dpair != 0b11):
                    m.next = "DT"


        #######################################################################
        # Clock and Data Recovery
        #
        # The DT state from the line state recovery state machine is used to align to
        # transmit clock.  The line state is sampled in the middle of the bit time.
        #
        # Example of signal relationships
        # -------------------------------
        # line_state        DT  DJ  DJ  DJ  DT  DK  DK  DK  DK  DK  DK  DT  DJ  DJ  DJ
        # line_state_valid  ________----____________----____________----________----____
        # bit_phase         0   0   1   2   3   0   1   2   3   0   1   2   0   1   2
        #

        # We 4x oversample, so make the line_state_phase have
        # 4 possible values.
        line_state_phase = Signal(2)
        m.d.usb_io += self.line_state_valid.eq(line_state_phase == 1)


        with m.If(line_state_in_transition):
            m.d.usb_io += [
                # re-align the phase with the incoming transition
                line_state_phase.eq(0),

                # make sure we never assert valid on a transition
                self.line_state_valid.eq(0),
            ]
        with m.Else():
            # keep tracking the clock by incrementing the phase
            m.d.usb_io += line_state_phase.eq(line_state_phase + 1)

        return m


class RxNRZIDecoder(Elaboratable):
    """RX NRZI decoder.

    In order to ensure there are enough bit transitions for a receiver to recover
    the clock usb uses NRZI encoding.  This module processes the incoming
    dj, dk, se0, and valid signals and decodes them to data values.  It
    also pipelines the se0 signal and passes it through unmodified.

    https://www.pjrc.com/teensy/beta/usb20.pdf, USB2 Spec, 7.1.8
    https://en.wikipedia.org/wiki/Non-return-to-zero

    Clock Domain
    ------------
    usb_48 : 48MHz

    Input Ports
    -----------
    Input ports are passed in via the constructor.

    i_valid : Signal(1)
        Qualifier for all of the input signals.  Indicates one bit of valid
        data is present on the inputs.

    i_dj : Signal(1)
        Indicates the bus is currently in a Full-Speed J-state.
        Qualified by valid.

    i_dk : Signal(1)
        Indicates the bus is currently in a Full-Speed K-state.
        Qualified by valid.

    i_se0 : Signal(1)
        Indicates the bus is currently in a SE0 state.
        Qualified by valid.

    Output Ports
    ------------
    Output ports are data members of the module. All output ports are flopped.

    o_valid : Signal(1)
        Qualifier for all of the output signals. Indicates one bit of valid
        data is present on the outputs.

    o_data : Signal(1)
        Decoded data bit from USB bus.
        Qualified by valid.

    o_se0 : Signal(1)
        Indicates the bus is currently in a SE0 state.
        Qualified by valid.
    """

    def __init__(self):
        self.i_valid = Signal()
        self.i_dj = Signal()
        self.i_dk = Signal()
        self.i_se0 = Signal()

        # pass all of the outputs through a pipe stage
        self.o_valid = Signal(1)
        self.o_data = Signal(1)
        self.o_se0 = Signal(1)


    def elaborate(self, platform):
        m = Module()

        last_data = Signal()
        with m.If(self.i_valid):
            m.d.usb_io += [
                last_data.eq(self.i_dk),
                self.o_data.eq(~(self.i_dk ^ last_data)),
                self.o_se0.eq((~self.i_dj) & (~self.i_dk)),
            ]
        m.d.usb_io += self.o_valid.eq(self.i_valid),

        return m


class RxPacketDetect(Elaboratable):
    """Packet Detection

    Full Speed packets begin with the following sequence:

        KJKJKJKK

    This raw sequence corresponds to the following data:

        00000001

    The bus idle condition is signaled with the J state:

        JJJJJJJJ

    This translates to a series of '1's since there are no transitions.  Given
    this information, it is easy to detect the beginning of a packet by looking
    for 00000001.

    The end of a packet is even easier to detect.  The end of a packet is
    signaled with two SE0 and one J.  We can just look for the first SE0 to
    detect the end of the packet.

    Packet detection can occur in parallel with bitstuff removal.

    https://www.pjrc.com/teensy/beta/usb20.pdf, USB2 Spec, 7.1.10

    Input Ports
    ------------
    i_valid : Signal(1)
        Qualifier for all of the input signals.  Indicates one bit of valid
        data is present on the inputs.

    i_data : Signal(1)
        Decoded data bit from USB bus.
        Qualified by valid.

    i_se0 : Signal(1)
        Indicator for SE0 from USB bus.
        Qualified by valid.

    Output Ports
    ------------
    o_pkt_start : Signal(1)
        Asserted for one clock on the last bit of the sync.

    o_pkt_active : Signal(1)
        Asserted while in the middle of a packet.

    o_pkt_end : Signal(1)
        Asserted for one clock after the last data bit of a packet was received.
    """

    def __init__(self):
        self.i_valid = Signal()
        self.i_data = Signal()
        self.i_se0 = Signal()

        self.o_pkt_start = Signal()
        self.o_pkt_active = Signal()
        self.o_pkt_end = Signal()


    def elaborate(self, platform):
        m = Module()

        pkt_start = Signal()
        pkt_active = Signal()
        pkt_end = Signal()

        with m.FSM(domain="usb_io"):

            for i in range(5):

                with m.State(f"D{i}"):
                    with m.If(self.i_valid):
                        with m.If(self.i_data | self.i_se0):
                            # Receiving '1' or SE0 early resets the packet start counter.
                            m.next = "D0"

                        with m.Else():
                            # Receiving '0' increments the packet start counter.
                            m.next = f"D{i + 1}"

            with m.State("D5"):
                with m.If(self.i_valid):
                    with m.If(self.i_se0):
                        m.next = "D0"
                    # once we get a '1', the packet is active
                    with m.Elif(self.i_data):
                        m.d.comb += pkt_start.eq(1)
                        m.next = "PKT_ACTIVE"

            with m.State("PKT_ACTIVE"):
                m.d.comb += pkt_active.eq(1)
                with m.If(self.i_valid & self.i_se0):
                    m.d.comb += [
                        pkt_active.eq(0),
                        pkt_end.eq(1)
                    ]
                    m.next = "D0"

        # pass all of the outputs through a pipe stage
        m.d.comb += [
            self.o_pkt_start.eq(pkt_start),
            self.o_pkt_active.eq(pkt_active),
            self.o_pkt_end.eq(pkt_end),
        ]

        return m



class RxBitstuffRemover(Elaboratable):
    """RX Bitstuff Removal

    Long sequences of 1's would cause the receiver to lose it's lock on the
    transmitter's clock.  USB solves this with bitstuffing.  A '0' is stuffed
    after every 6 consecutive 1's.  This extra bit is required to recover the
    clock, but it should not be passed on to higher layers in the device.

    https://www.pjrc.com/teensy/beta/usb20.pdf, USB2 Spec, 7.1.9
    https://en.wikipedia.org/wiki/Bit_stuffing

    Clock Domain
    ------------
    usb_48 : 48MHz

    Input Ports
    ------------
    i_valid : Signal(1)
        Qualifier for all of the input signals.  Indicates one bit of valid
        data is present on the inputs.

    i_data : Signal(1)
        Decoded data bit from USB bus.
        Qualified by valid.

    Output Ports
    ------------
    o_data : Signal(1)
        Decoded data bit from USB bus.

    o_stall : Signal(1)
        Indicates the bit stuffer just removed an extra bit, so no data available.

    o_error : Signal(1)
        Indicates there has been a bitstuff error. A bitstuff error occurs
        when there should be a stuffed '0' after 6 consecutive 1's; but instead
        of a '0', there is an additional '1'.  This is normal during IDLE, but
        should never happen within a packet.
        Qualified by valid.
    """

    def __init__(self):
        self.i_valid = Signal()
        self.i_data = Signal()

        # pass all of the outputs through a pipe stage
        self.o_data = Signal()
        self.o_error = Signal()
        self.o_stall = Signal(reset=1)


    def elaborate(self, platform):
        m = Module()

        # This state machine recognizes sequences of 6 bits and drops the 7th
        # bit.  The fsm implements a counter in a series of several states.
        # This is intentional to help absolutely minimize the levels of logic
        # used.
        drop_bit = Signal(1)


        with m.FSM(domain="usb_io"):

            for i in range(6):
                with m.State(f"D{i}"):
                    with m.If(self.i_valid):
                        with m.If(self.i_data):
                            # Receiving '1' increments the bitstuff counter.
                            m.next = (f"D{i + 1}")
                        with m.Else():
                            # Receiving '0' resets the bitstuff counter.
                            m.next = "D0"

            with m.State("D6"):
                with m.If(self.i_valid):
                    m.d.comb += drop_bit.eq(1)
                    # Reset the bitstuff counter, drop the data.
                    m.next = "D0"

        m.d.usb_io += [
            self.o_data.eq(self.i_data),
            self.o_stall.eq(drop_bit | ~self.i_valid),
            self.o_error.eq(drop_bit & self.i_data & self.i_valid),
        ]

        return m


class RxShifter(Elaboratable):
    """RX Shifter

    A shifter is responsible for shifting in serial bits and presenting them
    as parallel data.  The shifter knows how many bits to shift and has
    controls for resetting the shifter.

    Clock Domain
    ------------
    usb    : 12MHz

    Parameters
    ----------
    Parameters are passed in via the constructor.

    width : int
        Number of bits to shift in.

    Input Ports
    -----------
    i_valid : Signal(1)
        Qualifier for all of the input signals.  Indicates one bit of valid
        data is present on the inputs.

    i_data : Signal(1)
        Serial input data.
        Qualified by valid.

    Output Ports
    ------------
    o_data : Signal(width)
        Shifted in data.

    o_put : Signal(1)
        Asserted for one clock once the register is full.
    """
    def __init__(self, width):
        self._width = width

        #
        # I/O port
        #
        self.reset   = Signal()

        self.i_valid = Signal()
        self.i_data  = Signal()

        self.o_data  = Signal(width)
        self.o_put   = Signal()


    def elaborate(self, platform):
        m = Module()
        width = self._width

        # Instead of using a counter, we will use a sentinel bit in the shift
        # register to indicate when it is full.
        shift_reg = Signal(width+1, reset=0b1)

        m.d.comb += self.o_data.eq(shift_reg[0:width])
        m.d.usb_io += self.o_put.eq(shift_reg[width-1] & ~shift_reg[width] & self.i_valid),

        with m.If(self.reset):
            m.d.usb_io += shift_reg.eq(1)

        with m.If(self.i_valid):
            with m.If(shift_reg[width]):
                m.d.usb_io += shift_reg.eq(Cat(self.i_data, Const(1)))
            with m.Else():
                m.d.usb_io += shift_reg.eq(Cat(self.i_data, shift_reg[0:width])),

        return m


class RxPipeline(Elaboratable):

    def __init__(self):
        self.reset = Signal()

        # 12MHz USB alignment pulse in 48MHz clock domain
        self.o_bit_strobe = Signal()

        # Reset state is J
        self.i_usbp = Signal(reset=1)
        self.i_usbn = Signal(reset=0)

        self.o_data_strobe = Signal()
        self.o_data_payload = Signal(8)

        self.o_pkt_start = Signal()
        self.o_pkt_in_progress = Signal()
        self.o_pkt_end = Signal()

        self.o_receive_error = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # Clock/Data recovery.
        #
        clock_data_recovery = RxClockDataRecovery(self.i_usbp, self.i_usbn)
        m.submodules.clock_data_recovery = clock_data_recovery
        m.d.comb += self.o_bit_strobe.eq(clock_data_recovery.line_state_valid)

        #
        # NRZI decoding
        #
        m.submodules.nrzi = nrzi = RxNRZIDecoder()
        m.d.comb += [
            nrzi.i_valid  .eq(self.o_bit_strobe),
            nrzi.i_dj     .eq(clock_data_recovery.line_state_dj),
            nrzi.i_dk     .eq(clock_data_recovery.line_state_dk),
            nrzi.i_se0    .eq(clock_data_recovery.line_state_se0),
        ]

        #
        # Packet boundary detection.
        #
        m.submodules.detect = detect = ResetInserter(self.reset)(RxPacketDetect())
        m.d.comb += [
            detect.i_valid  .eq(nrzi.o_valid),
            detect.i_se0    .eq(nrzi.o_se0),
            detect.i_data   .eq(nrzi.o_data),
        ]

        #
        # Bitstuff remover.
        #
        m.submodules.bitstuff = bitstuff = \
            ResetInserter(~detect.o_pkt_active)(RxBitstuffRemover())
        m.d.comb += [
            bitstuff.i_valid.eq(nrzi.o_valid),
            bitstuff.i_data.eq(nrzi.o_data),
            self.o_receive_error.eq(bitstuff.o_error)
        ]

        #
        # 1bit->8bit (1byte) gearing
        #
        m.submodules.shifter = shifter = RxShifter(width=8)
        m.d.comb += [
            shifter.reset.eq(detect.o_pkt_end),
            shifter.i_data.eq(bitstuff.o_data),
            shifter.i_valid.eq(~bitstuff.o_stall & Past(detect.o_pkt_active, domain="usb_io")),
        ]

        #
        # Clock domain crossing.
        #
        flag_start  = Signal()
        flag_end    = Signal()
        flag_valid  = Signal()
        m.submodules.payload_fifo = payload_fifo = AsyncFIFOBuffered(width=8, depth=4, r_domain="usb", w_domain="usb_io")
        m.d.comb += [
            payload_fifo.w_data  .eq(shifter.o_data[::-1]),
            payload_fifo.w_en    .eq(shifter.o_put),
            self.o_data_payload  .eq(payload_fifo.r_data),
            self.o_data_strobe   .eq(payload_fifo.r_rdy),
            payload_fifo.r_en    .eq(1)
        ]

        m.submodules.flags_fifo = flags_fifo = AsyncFIFOBuffered(width=2, depth=4, r_domain="usb", w_domain="usb_io")
        m.d.comb += [
            flags_fifo.w_data[1]  .eq(detect.o_pkt_start),
            flags_fifo.w_data[0]  .eq(detect.o_pkt_end),
            flags_fifo.w_en       .eq(detect.o_pkt_start | detect.o_pkt_end),

            flag_start            .eq(flags_fifo.r_data[1]),
            flag_end              .eq(flags_fifo.r_data[0]),
            flag_valid            .eq(flags_fifo.r_rdy),
            flags_fifo.r_en       .eq(1),
        ]

        # Packet flag signals (in 12MHz domain)
        m.d.comb += [
            self.o_pkt_start  .eq(flag_start & flag_valid),
            self.o_pkt_end    .eq(flag_end & flag_valid),
        ]

        with m.If(self.o_pkt_start):
            m.d.usb += self.o_pkt_in_progress.eq(1)
        with m.Elif(self.o_pkt_end):
            m.d.usb += self.o_pkt_in_progress.eq(0)

        return m

