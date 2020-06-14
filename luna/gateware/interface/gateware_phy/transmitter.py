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

from nmigen          import Elaboratable, Module, Signal, Cat, Const
from nmigen.lib.cdc  import FFSynchronizer

# TODO: these should be removed during the nMigen'ification
from nmigen.hdl.xfrm import DomainRenamer, ResetInserter, EnableInserter
from nmigen.compat   import FSM, If, NextState, NextValue, Case



class TxShifter(Elaboratable):
    """Transmit Shifter

    TxShifter accepts parallel data and shifts it out serially.

    Parameters
    ----------
    Parameters are passed in via the constructor.

    width : int
        Width of the data to be shifted.

    Input Ports
    -----------
    Input ports are passed in via the constructor.

    i_data : Signal(width)
        Data to be transmitted.

    Output Ports
    ------------
    Output ports are data members of the module. All outputs are flopped.

    o_data : Signal(1)
        Serial data output.

    o_empty : Signal(1)
        Asserted the cycle before the shifter loads in more i_data.

    o_get : Signal(1)
        Asserted the cycle after the shifter loads in i_data.

    """
    def __init__(self, width):
        self._width = width

        #
        # I/O Port
        #
        self.i_data = Signal(width)
        self.o_get = Signal(1)
        self.o_empty = Signal(1)

        self.o_data = Signal(1)


    def elaborate(self, platform):
        m = Module()

        shifter = Signal(self._width)
        pos = Signal(self._width, reset=0b1)

        empty = Signal(1)
        m.d.sync += [
            pos.eq(pos >> 1),
            shifter.eq(shifter >> 1),
            self.o_get.eq(empty),
        ]

        with m.If(empty):
            m.d.sync += [
                shifter.eq(self.i_data),
                pos.eq(1 << (self._width-1)),
            ]

        m.d.comb += [
            empty.eq(pos[0]),
            self.o_empty.eq(empty),
            self.o_data.eq(shifter[0]),
        ]

        return m



class TxNRZIEncoder(Elaboratable):
    """
    NRZI Encode

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
    i_valid : Signal(1)
        Qualifies oe, data, and se0.

    i_oe : Signal(1)
        Indicates that the transmit pipeline should be driving USB.

    i_data : Signal(1)
        Data bit to be transmitted on USB. Qualified by o_valid.

    i_se0 : Signal(1)
        Overrides value of o_data when asserted and indicates that SE0 state
        should be asserted on USB. Qualified by o_valid.

    Output Ports
    ------------
    o_usbp : Signal(1)
        Raw value of USB+ line.

    o_usbn : Signal(1)
        Raw value of USB- line.

    o_oe : Signal(1)
        When asserted it indicates that the tx pipeline should be driving USB.
    """

    def __init__(self):
        self.i_valid = Signal()
        self.i_oe = Signal()
        self.i_data = Signal()

        # flop all outputs
        self.o_usbp = Signal(1)
        self.o_usbn = Signal(1)
        self.o_oe = Signal(1)


    def elaborate(self, platform):
        m = Module()

        # Simple state machine to perform NRZI encoding.
        m.submodules.nrzi = nrzi = FSM()

        usbp = Signal(1)
        usbn = Signal(1)
        oe = Signal(1)

        # wait for new packet to start
        nrzi.act("IDLE",
            usbp.eq(1),
            usbn.eq(0),
            oe.eq(0),

            If(self.i_valid,
                If(self.i_oe,
                    # first bit of sync always forces a transition, we idle
                    # in J so the first output bit is K.
                    NextState("DK")
                )
            )
        )

        # the output line is in state J
        nrzi.act("DJ",
            usbp.eq(1),
            usbn.eq(0),
            oe.eq(1),

            If(self.i_valid,
                If(~self.i_oe,
                    NextState("SE0A")
                ).Elif(self.i_data,
                    NextState("DJ")
                ).Else(
                    NextState("DK")
                )
            )
        )

        # the output line is in state K
        nrzi.act("DK",
            usbp.eq(0),
            usbn.eq(1),
            oe.eq(1),

            If(self.i_valid,
                If(~self.i_oe,
                    NextState("SE0A")
                ).Elif(self.i_data,
                    NextState("DK")
                ).Else(
                    NextState("DJ")
                )
            )
        )

        # first bit of the SE0 state
        nrzi.act("SE0A",
            usbp.eq(0),
            usbn.eq(0),
            oe.eq(1),

            If(self.i_valid,
                NextState("SE0B")
            )
        )
        # second bit of the SE0 state
        nrzi.act("SE0B",
            usbp.eq(0),
            usbn.eq(0),
            oe.eq(1),

            If(self.i_valid,
                NextState("EOPJ")
            )
        )

        # drive the bus back to J before relinquishing control
        nrzi.act("EOPJ",
            usbp.eq(1),
            usbn.eq(0),
            oe.eq(1),

            If(self.i_valid,
                NextState("IDLE")
            )
        )


        m.d.sync += [
            self.o_oe.eq(oe),
            self.o_usbp.eq(usbp),
            self.o_usbn.eq(usbn),
        ]

        return m


class TxBitstuffer(Elaboratable):
    """
    Bitstuff Insertion

    Long sequences of 1's would cause the receiver to lose it's lock on the
    transmitter's clock.  USB solves this with bitstuffing.  A '0' is stuffed
    after every 6 consecutive 1's.

    The TxBitstuffer is the only component in the transmit pipeline that can
    delay transmission of serial data.  It is therefore responsible for
    generating the bit_strobe signal that keeps the pipe moving forward.

    https://www.pjrc.com/teensy/beta/usb20.pdf, USB2 Spec, 7.1.9
    https://en.wikipedia.org/wiki/Bit_stuffing

    Clock Domain
    ------------
    usb_12 : 48MHz

    Input Ports
    ------------
    i_data : Signal(1)
        Data bit to be transmitted on USB.

    Output Ports
    ------------
    o_data : Signal(1)
        Data bit to be transmitted on USB.

    o_stall : Signal(1)
        Used to apply backpressure on the tx pipeline.
    """
    def __init__(self):
        self.i_data = Signal()

        self.o_stall = Signal(1)
        self.o_will_stall = Signal(1)
        self.o_data = Signal(1)


    def elaborate(self, platform):
        m = Module()

        m.submodules.stuff = stuff = FSM()

        stuff_bit = Signal(1)

        for i in range(5):
            stuff.act("D%d" % i,
                If(self.i_data,
                    # Receiving '1' increments the bitstuff counter.
                    NextState("D%d" % (i + 1))
                ).Else(
                    # Receiving '0' resets the bitstuff counter.
                    NextState("D0")
                )
            )

        stuff.act("D5",
            If(self.i_data,
                # There's a '1', so indicate we might stall on the next loop.
                self.o_will_stall.eq(1),

                # Receiving '1' increments the bitstuff counter.
                NextState("D6")
            ).Else(
                # Receiving '0' resets the bitstuff counter.
                NextState("D0")
            )
        )

        stuff.act("D6",
            # stuff a bit
            stuff_bit.eq(1),

            # Reset the bitstuff counter
            NextState("D0")
        )

        m.d.comb += [
            self.o_stall.eq(stuff_bit)
        ]

        # flop outputs
        with m.If(stuff_bit):
            m.d.sync += self.o_data.eq(0),
        with m.Else():
            m.d.sync += self.o_data.eq(self.i_data)

        return m


class TxPipeline(Elaboratable):
    def __init__(self):
        self.i_bit_strobe = Signal()

        self.i_data_payload = Signal(8)
        self.o_data_strobe = Signal()

        self.i_oe = Signal()

        self.o_usbp = Signal()
        self.o_usbn = Signal()
        self.o_oe = Signal()

        self.o_pkt_end = Signal()


        self.fit_dat = Signal()
        self.fit_oe  = Signal()


    def elaborate(self, platform):
        m = Module()

        sync_pulse = Signal(8)

        da_reset_shifter = Signal()
        da_reset_bitstuff = Signal() # Need to reset the bit stuffer 1 cycle after the shifter.
        stall = Signal()

        # These signals are set during the sync pulse
        sp_reset_bitstuff = Signal()
        sp_reset_shifter = Signal()
        sp_bit = Signal()
        sp_o_data_strobe = Signal()

        # 12MHz domain

        da_stalled_reset = Signal()
        bitstuff_valid_data = Signal()

        # Keep a Gray counter around to smoothly transition between states
        state_gray = Signal(2)
        state_data = Signal()
        state_sync = Signal()


        tx_pipeline_fsm = FSM()
        m.submodules.tx_pipeline_fsm = DomainRenamer({"sync": "usb"})(tx_pipeline_fsm)

        shifter = EnableInserter(~stall)(ResetInserter(da_reset_shifter | sp_reset_shifter)(TxShifter(width=8)))
        m.submodules.shifter = DomainRenamer({"sync": "usb"})(shifter)

        bitstuff = ResetInserter(da_reset_bitstuff)(TxBitstuffer())
        m.submodules.bitstuff = DomainRenamer({"sync": "usb"})(bitstuff)

        nrzi = TxNRZIEncoder()
        m.submodules.nrzi = DomainRenamer({"sync": "usb_io"})(nrzi)


        m.d.comb += [
            shifter.i_data.eq(self.i_data_payload),
            # Send a data strobe when we're two bits from the end of the sync pulse.
            # This is because the pipeline takes two bit times, and we want to ensure the pipeline
            # has spooled up enough by the time we're there.


            bitstuff.i_data.eq(shifter.o_data),
            stall.eq(bitstuff.o_stall),

            sp_bit.eq(sync_pulse[0]),
            sp_reset_bitstuff.eq(sync_pulse[0]),

            # The shifter has one clock cycle of latency, so reset it
            # one cycle before the end of the sync byte.
            sp_reset_shifter.eq(sync_pulse[1]),

            sp_o_data_strobe.eq(sync_pulse[5]),

            state_data.eq(state_gray[0] & state_gray[1]),
            state_sync.eq(state_gray[0] & ~state_gray[1]),

            self.fit_oe.eq(state_data | state_sync),
            self.fit_dat.eq((state_data & shifter.o_data & ~bitstuff.o_stall) | sp_bit),
            self.o_data_strobe.eq((state_data & shifter.o_get & ~stall & self.i_oe) | sp_o_data_strobe),
        ]

        # If we reset the shifter, then o_empty will go high on the next cycle.
        #

        m.d.usb += [
            # If the shifter runs out of data, percolate the "reset" signal to the
            # shifter, and then down to the bitstuffer.
            # da_reset_shifter.eq(~stall & shifter.o_empty & ~da_stalled_reset),
            # da_stalled_reset.eq(da_reset_shifter),
            # da_reset_bitstuff.eq(~stall & da_reset_shifter),
            bitstuff_valid_data.eq(~stall & shifter.o_get & self.i_oe),
        ]

        tx_pipeline_fsm.act('IDLE',
            If(self.i_oe,
                NextState('SEND_SYNC'),
                NextValue(sync_pulse, 1 << 7),
                NextValue(state_gray, 0b01),
            ).Else(
                NextValue(state_gray, 0b00),
            )
        )

        tx_pipeline_fsm.act('SEND_SYNC',
            NextValue(sync_pulse, sync_pulse >> 1),

            If(sync_pulse[0],
                NextState('SEND_DATA'),
                NextValue(state_gray, 0b11),
            ).Else(
                NextValue(state_gray, 0b01),
            ),
        )

        tx_pipeline_fsm.act('SEND_DATA',
            If(~self.i_oe & shifter.o_empty & ~bitstuff.o_stall,
                If(bitstuff.o_will_stall,
                    NextState('STUFF_LAST_BIT')
                ).Else(
                    NextValue(state_gray, 0b10),
                    NextState('IDLE'),
                )
            ).Else(
                NextValue(state_gray, 0b11),
            ),
        )

        tx_pipeline_fsm.act('STUFF_LAST_BIT',
            NextValue(state_gray, 0b10),
            NextState('IDLE'),
        )

        # 48MHz domain
        # NRZI encoding
        nrzi_dat = Signal()
        nrzi_oe = Signal()

        # Cross the data from the 12MHz domain to the 48MHz domain
        cdc_dat = FFSynchronizer(self.fit_dat, nrzi_dat, o_domain="usb_io", stages=3)
        cdc_oe  = FFSynchronizer(self.fit_oe, nrzi_oe, o_domain="usb_io", stages=3)
        m.submodules += [cdc_dat, cdc_oe]

        m.d.comb += [
            nrzi.i_valid.eq(self.i_bit_strobe),
            nrzi.i_data.eq(nrzi_dat),
            nrzi.i_oe.eq(nrzi_oe),

            self.o_usbp.eq(nrzi.o_usbp),
            self.o_usbn.eq(nrzi.o_usbn),
            self.o_oe.eq(nrzi.o_oe),
        ]

        return m
