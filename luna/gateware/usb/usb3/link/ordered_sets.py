#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based on ``litex`` and ``usb3_pipe``.
# SPDX-License-Identifier: BSD-3-Clause
""" Link training support gateware.

Note that much of the gateware in this module is written big endian;
as this makes the test sets match the standard. This is handled automatically
by the link layer gateware.
"""

from nmigen import *

from ..physical.coding import D, COM
from ...stream         import USBRawSuperSpeedStream

TS1_SET_ID = D(10, 2)
TS2_SET_ID = D(5,  2)

#
# Training set contents.
#
TSEQ_SET_DATA = [
    0xBCFF17C0, # 0  - 3
    0x14B2E702, # 4  - 7
    0x82726E28, # 8  - 11
    0xA6BE6DBF, # 12 - 15
    0x4A4A4A4A, # 16 - 19
    0x4A4A4A4A, # 20 - 23
    0x4A4A4A4A, # 24 - 27
    0x4A4A4A4A, # 28 - 31
]

TS1_SET_DATA = [
    0xBCBCBCBC, # 0  - 3
    0x00004A4A, # 4  - 7
    0x4A4A4A4A, # 16 - 19
    0x4A4A4A4A, # 20 - 23
]

TS2_SET_DATA = [
    0xBCBCBCBC, # 0  - 3
    0x00004545, # 4  - 7
    0x45454545, # 16 - 19
    0x45454545, # 20 - 23
]


class TSBurstDetector(Elaboratable):
    """ Simple Training Set detector; capable of detecting basic training sets. """

    # TODO: allow masking of the second word

    def __init__(self, *, set_data, first_word_ctrl, sets_in_burst=1, invert_data=False, include_config=True):
        self._set_data            = set_data
        self._first_word_ctrl     = first_word_ctrl
        self._detection_threshold = sets_in_burst
        self._invert_data         = invert_data
        self._include_config      = include_config

        #
        # I/O port
        #
        self.sink                 = USBRawSuperSpeedStream()
        self.detected             = Signal() # o
        self.error                = Signal() # o

        if self._include_config:
            self.hot_reset            = Signal()
            self.loopback_requested   = Signal()
            self.disable_scrambling   = Signal()


    def elaborate(self, platform):
        m = Module()
        m.d.ss += self.detected.eq(0)

        # Always accept data from our SerDes.
        m.d.comb += self.sink.ready.eq(1)

        # Counter that tracks how many consecutive sets we've received.
        consecutive_set_count = Signal(range(0, self._detection_threshold + 1))

        # Aliases.
        data  = self.sink.data
        ctrl  = self.sink.ctrl


        def advance_on_match(count, target_ctrl=0b0000, fail_state="NONE_DETECTED"):
            data_matches = (data  == self._set_data[count])
            data_inverse = (~data == self._set_data[count])
            ctrl_matches = (ctrl == target_ctrl)

            # If we're using the inverted set, use ``data_inverse`` instead of ``data_matches``.
            if self._invert_data:
                data_matches = data_inverse

            # Once we have a valid word in our stream...
            with m.If(self.sink.valid):

                # ... advance if that word matches; or move to our "fail state" otherwise.
                with m.If(data_matches & ctrl_matches):
                    m.next = f"{count + 1}_DETECTED"
                with m.Else():
                    m.next = fail_state


        last_state_number = len(self._set_data)
        with m.FSM(domain="ss"):

            # NONE_DETECTED -- we haven't seen any parts of our ordered set;
            # we're waiting for the first one.
            with m.State("NONE_DETECTED"):
                m.d.ss += consecutive_set_count.eq(0)
                m.next = "WAIT_FOR_FIRST"

            # WAIT_FOR_FIRST -- we're waiting to see the first word of our sequence
            with m.State("WAIT_FOR_FIRST"):
                advance_on_match(0, target_ctrl=self._first_word_ctrl, fail_state="WAIT_FOR_FIRST")

            # 1_DETECTED -- we're parsing the first data word; which we'll do slightly differently,
            # as it can contain a variable configuration field.
            with m.State("1_DETECTED"):
                # If this set includes a configuration field, then we'll want to compare
                # our data with that set removed. Otherwise, we compare normally.
                data_masked  = (data & 0xffff) if self._include_config else data
                data_matches = (data_masked  == self._set_data[1])
                data_inverse = (~data_masked == self._set_data[1])
                ctrl_matches = (ctrl         == 0)

                # If we're using the inverted set, use ``data_inverse`` instead of ``data_matches``.
                if self._invert_data:
                    data_matches = data_inverse

                # Once we have a valid word in our stream...
                with m.If(self.sink.valid):

                    # ... advance if that word matches; or move to our "fail state" otherwise.
                    with m.If(data_matches & ctrl_matches):
                        m.next = f"2_DETECTED"

                        # If we're including a configuration field, parse it before we continue.
                        if self._include_config:
                            m.d.ss += [
                                # Bit 0 of Symbol 5 => Hot Reset
                                self.hot_reset           .eq(data.word_select(2, 8)[0]),

                                # Bit 2 of Symbol 5 => Requests Loopback Mode
                                self.loopback_requested  .eq(data.word_select(2, 8)[2]),

                                # Bit 3 of Symbol 5 = > Requests we not use scrambling.
                                self.disable_scrambling  .eq(data.word_select(2, 8)[3]),
                            ]

                    with m.Else():
                        m.next = "NONE_DETECTED"


            for i in range(2, last_state_number):
                with m.State(f"{i}_DETECTED"):
                    advance_on_match(i)


            with m.State(f"{last_state_number}_DETECTED"):

                # If we've seen as many sets as we're looking to detect, reset our count,
                # and indicate that we've completed a detection.
                with m.If(consecutive_set_count + 1 == self._detection_threshold):
                    m.d.ss   += [
                        consecutive_set_count  .eq(0),
                        self.detected          .eq(1)
                    ]

                # Otherwise, increase the number of consecutive sets seen.
                with m.Else():
                    m.d.ss += consecutive_set_count.eq(consecutive_set_count + 1)

                with m.If(self.sink.valid):
                    advance_on_match(0, target_ctrl=self._first_word_ctrl)
                with m.Else():
                    m.next = "WAIT_FOR_FIRST"


        return m



class TSEmitter(Elaboratable):
    """ Training Set Emitter

    Generic Training Sequence Ordered Set generator.

    This module generates a specific Training Sequence Ordered Set to the TX stream. For each start,
    N consecutive Ordered Sets are generated (N configured by n_ordered_sets). Done signal is assert
    on the last cycle of the generation. Training config can also be transmitted for TS1/TS2 Ordered
    Sets.
    """
    def __init__(self, *, set_data, first_word_ctrl=0b1111, transmit_burst_length=1, include_config=False):
        self._set_data          = set_data
        self._first_word_ctrl   = first_word_ctrl
        self._total_to_transmit = transmit_burst_length
        self._include_config    = include_config

        #
        # I/O port
        #
        self.source            = USBRawSuperSpeedStream()

        self.start             = Signal()
        self.done              = Signal()

        if self._include_config:
            self.request_hot_reset = Signal()



    def elaborate(self, platform):
        m = Module()

        # Keep track of how many ordered sets we've sent.
        sent_ordered_sets = Signal(range(self._total_to_transmit))
        m.d.comb += self.done.eq(sent_ordered_sets == self._total_to_transmit)

        with m.FSM(domain="ss"):

            # IDLE - we're currently waiting for a ``start`` request.=
            with m.State("IDLE"):

                # Once we get our start request, start blasting out our words in order.
                with m.If(self.start):
                    m.next = "WORD_0"

            # Sequentially output each word of our training set.
            for i in range(len(self._set_data)):
                with m.State(f"WORD_{i}"):
                    is_last_word = (i + 1 == len(self._set_data))
                    m.d.comb += [
                        self.source.valid  .eq(1),
                        self.source.data   .eq(self._set_data[i]),
                        self.source.ctrl   .eq(self._first_word_ctrl if i == 0 else 0b0000),
                        self.source.first  .eq(i == 0),
                        self.source.last   .eq(is_last_word)
                    ]

                    # If this is the first data word of our Training Set, we'll optionally set
                    # our control fields.
                    if self._include_config and (i == 1):
                        with m.If(self.request_hot_reset):
                            m.d.comb += self.source.data.word_select(2, 8).eq(1)


                    with m.If(self.source.ready):
                        # If we're generating the state for the last word,
                        # we also have to handle our count.
                        if is_last_word:
                            # If we've just reached the total number of sets, we're done!
                            # Reset our count to zero, and indicate done-ness.
                            with m.If(sent_ordered_sets + 1 == self._total_to_transmit):
                                m.d.comb += self.done.eq(1)
                                m.d.ss   += sent_ordered_sets.eq(0)

                                # If we're still requesting data be sent, restart from the first word.
                                with m.If(self.start):
                                    m.next = "WORD_0"
                                # Otherwise, return to idle until we receive ``start`` again`.
                                with m.Else():
                                    m.next = "IDLE"

                            # If we're not yet done transmitting our full set, continue.
                            with m.Else():
                                m.d.ss += sent_ordered_sets.eq(sent_ordered_sets + 1)
                                m.next = "WORD_0"

                        else:
                            m.next = f"WORD_{i+1}"

        return m


class TSTransceiver(Elaboratable):
    """Training Sequence Unit

    Detect/generate the Training Sequence Ordered Sets required for a USB3.0 link with simple
    control/status signals.
    """
    def __init__(self):

        #
        # I/O port
        #
        self.sink       = USBRawSuperSpeedStream()
        self.source     = USBRawSuperSpeedStream()

        # Detectors
        self.tseq_detected         = Signal() # o
        self.ts1_detected          = Signal() # o
        self.inverted_ts1_detected = Signal() # o
        self.ts2_detected          = Signal() # o

        self.hot_reset_requested   = Signal()
        self.loopback_requested    = Signal()
        self.disable_scrambling    = Signal()

        # Emitters
        self.send_tseq_burst       = Signal() # i
        self.send_ts1_burst        = Signal() # i
        self.send_ts2_burst        = Signal() # i
        self.transmitting          = Signal() # o
        self.burst_complete        = Signal() # o

        self.request_hot_reset     = Signal()


    def elaborate(self, platform):
        m = Module()

        #
        # TSEQ Detectors
        #

        # We're always ready to accept data.
        m.d.comb += self.sink.ready.eq(1)

        # TSEQ detector (not strictly required, but useful for alignment)
        m.submodules.tseq_detector = tseq_detector = TSBurstDetector(
            set_data        = TSEQ_SET_DATA,
            first_word_ctrl = 0b1000,
            sets_in_burst   = 32,
            include_config  = False
        )
        m.d.comb += [
            tseq_detector.sink  .stream_eq(self.sink, omit={"ready"}),
            self.tseq_detected  .eq(tseq_detector.detected)
        ]

        # TS1 detector
        m.submodules.ts1_detector = ts1_detector = TSBurstDetector(
            set_data        = TS1_SET_DATA,
            first_word_ctrl = 0b1111,
            sets_in_burst   = 8
        )
        m.d.comb += [
            ts1_detector.sink  .tap(self.sink),
            self.ts1_detected  .eq(ts1_detector.detected)
        ]

        # Inverted TS1 detector
        m.submodules.inverted_ts1_detector = inverted_ts1_detector = TSBurstDetector(
            set_data        = TS1_SET_DATA,
            first_word_ctrl = 0b1111,
            sets_in_burst   = 8,
            invert_data     = True,
        )
        m.d.comb += [
            inverted_ts1_detector.sink  .tap(self.sink),
            self.inverted_ts1_detected  .eq(inverted_ts1_detector.detected)
        ]

        # TS2 detector
        m.submodules.ts2_detector = ts2_detector = TSBurstDetector(
            set_data        = TS2_SET_DATA,
            first_word_ctrl = 0b1111,
            sets_in_burst   = 8,
        )
        m.d.comb += [
            ts2_detector.sink  .tap(self.sink),
            self.ts2_detected  .eq(ts2_detector.detected),

            self.hot_reset_requested  .eq(ts2_detector.hot_reset),
            self.loopback_requested   .eq(ts2_detector.loopback_requested),
            self.disable_scrambling   .eq(ts2_detector.loopback_requested),
        ]


        #
        # Ordered set generators
        #

        # TSEQ generator
        m.submodules.tseq_generator = tseq_generator = TSEmitter(
            set_data              = TSEQ_SET_DATA,
            first_word_ctrl       = 0b1000,
            transmit_burst_length = 65536
        )
        with m.If(self.send_tseq_burst):
            m.d.comb += [
                tseq_generator.start  .eq(1),
                self.source           .stream_eq(tseq_generator.source)
            ]

        # TS1 generator
        m.submodules.ts1_generator = ts1_generator = TSEmitter(
            set_data              = TS1_SET_DATA,
            first_word_ctrl       = 0b1111,
            transmit_burst_length = 16
        )
        with m.If(self.send_ts1_burst):
            m.d.comb += [
                ts1_generator.start  .eq(1),
                self.source          .stream_eq(ts1_generator.source)
            ]

        # TS2 Generator
        m.submodules.ts2_generator = ts2_generator = TSEmitter(
            set_data              = TS2_SET_DATA,
            first_word_ctrl       = 0b1111,
            transmit_burst_length = 16,
            include_config        = True,
        )
        with m.If(self.send_ts2_burst):
            m.d.comb += [
                ts2_generator.start              .eq(1),
                ts2_generator.request_hot_reset  .eq(self.request_hot_reset),
                self.source                      .stream_eq(ts2_generator.source),
            ]

        #
        # Status signals.
        #
        tseq_transmitting = tseq_generator.source.valid
        ts1_transmitting  = ts1_generator.source.valid
        ts2_transmitting  = ts2_generator.source.valid
        m.d.comb += [
            self.transmitting   .eq(tseq_transmitting   | ts1_transmitting   | ts2_transmitting),
            self.burst_complete .eq(tseq_generator.done | ts1_generator.done | ts2_generator.done),
        ]

        return m
