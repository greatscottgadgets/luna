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


class TSDetector(Elaboratable):
    """ Simple Training Set detector; capable of detecting TS1/TS2 training sets. """

    # Our "start of set" is four COM symbols.
    START_OF_SET = Repl(COM.value, 4)

    def __init__(self, ordered_set_id, n_ordered_sets=1, invert=False):
        self._raw_set_id          = ordered_set_id
        self._set_id              = Const(ordered_set_id, shape=8)
        self._detection_threshold = n_ordered_sets
        self._invert              = invert

        #
        # I/O port
        #
        self.sink     = USBRawSuperSpeedStream()
        self.detected = Signal() # o
        self.error    = Signal() # o

        self.reset      = Signal()        # o
        self.loopback   = Signal()        # o
        self.scrambling = Signal(reset=1) # o


    def elaborate(self, platform):
        m = Module()
        m.d.ss += self.detected.eq(0)

        # Always accept data from our SerDes.
        m.d.comb += self.sink.ready.eq(1)

        # Counter that tracks how many consecutive sets we've received.
        consecutive_set_count = Signal(range(0, self._detection_threshold + 1))

        # Aliases.
        data         = ~self.sink.data if self._invert else self.sink.data
        control_bits = self.sink.ctrl

        # TODO: also check the control bits, here
        is_control_word = (control_bits == 0b1111)
        is_data_word    = (control_bits == 0b0000)
        word_starts_set = (data == self.START_OF_SET) & is_control_word


        with m.FSM(domain="ss"):

            # NONE_DETECTED -- we haven't seen any parts of our ordered set;
            # we're waiting for the first one.
            with m.State("NONE_DETECTED"):
                m.d.ss += consecutive_set_count.eq(0)
                m.next = "WAIT_FOR_FIRST"


            with m.State("WAIT_FOR_FIRST"):

                # Once we see the four COM symbols that start our training set,
                # move to checking the second word.
                with m.If(self.sink.valid):
                    with m.If(word_starts_set):
                        m.next = "ONE_DETECTED"


            # ONE_DETECTED -- we're now inside a suspected training set; we'll
            # validate the second word.
            with m.State("ONE_DETECTED"):

                with m.If(self.sink.valid):

                    # The second word of our training set has a "link training" field
                    # as its second byte; so we'll skip checking it.
                    with m.If(data[16:] == Repl(self._set_id, 2)):
                        m.next = "TWO_DETECTED"
                    with m.Else():
                        m.next = "NONE_DETECTED"

                    m.next = "TWO_DETECTED"

            # TWO_DETECTED -- we're now inside a suspected training set; we'll
            # validate the third word.
            with m.State("TWO_DETECTED"):

                with m.If(self.sink.valid):

                    with m.If(data == Repl(self._set_id, 4)):
                        m.next = "THREE_DETECTED"
                    with m.Else():
                        m.next = "NONE_DETECTED"


            # THREE_DETECTED -- we're now inside a suspected training set; we'll
            # validate the third word.
            with m.State("THREE_DETECTED"):
                with m.If(self.sink.valid):
                    with m.If(data == Repl(self._set_id, 4)):
                        m.next = "SET_DETECTED"
                    with m.Else():
                        m.next = "NONE_DETECTED"


            with m.State("SET_DETECTED"):

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
                    # If we're now starting a new consecutive set, move right into detecting
                    # this new set. Otherwise, clear our detection status.
                    with m.If(word_starts_set):
                        m.next = "ONE_DETECTED"
                    with m.Else():
                        m.next = "NONE_DETECTED"

                with m.Else():
                    m.next = "WAIT_FOR_FIRST"


        return m


class TSBurstDetector(Elaboratable):
    """ Simple Training Set detector; capable of detecting basic training sets. """

    # TODO: allow masking of the second word

    def __init__(self, *, set_data, first_word_ctrl, sets_in_burst=1, invert_data=False):
        self._set_data            = set_data
        self._first_word_ctrl     = first_word_ctrl
        self._detection_threshold = sets_in_burst
        self._invert_data         = invert_data

        #
        # I/O port
        #
        self.sink       = USBRawSuperSpeedStream()
        self.detected   = Signal() # o
        self.error      = Signal() # o

        self.reset      = Signal()        # o
        self.loopback   = Signal()        # o
        self.scrambling = Signal(reset=1) # o


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


            with m.State("WAIT_FOR_FIRST"):
                advance_on_match(0, target_ctrl=self._first_word_ctrl, fail_state="WAIT_FOR_FIRST")


            for i in range(1, last_state_number):
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
    def __init__(self, *, set_data, first_word_ctrl=0b1111, transmit_burst_length=1):
        self._set_data          = set_data
        self._first_word_ctrl   = first_word_ctrl
        self._total_to_transmit = transmit_burst_length

        #
        # I/O port
        #
        self.start  = Signal() # i
        self.done   = Signal() # o

        self.source = USBRawSuperSpeedStream()


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

        # Emitters
        self.send_tseq_burst       = Signal() # i
        self.send_ts1_burst        = Signal() # i
        self.send_ts2_burst        = Signal() # i
        self.transmitting          = Signal() # o
        self.burst_complete        = Signal() # o


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
            sets_in_burst   = 32
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
            ts1_detector.sink  .stream_eq(self.sink, omit={"ready"}),
            self.ts1_detected  .eq(ts1_detector.detected)
        ]

        # Inverted TS1 detector
        m.submodules.inverted_ts1_detector = inverted_ts1_detector = TSBurstDetector(
            set_data        = TS1_SET_DATA,
            first_word_ctrl = 0b1111,
            sets_in_burst   = 8,
            invert_data     = True
        )
        m.d.comb += [
            inverted_ts1_detector.sink  .stream_eq(self.sink, omit={"ready"}),
            self.inverted_ts1_detected  .eq(inverted_ts1_detector.detected)
        ]

        # TS2 detector
        m.submodules.ts2_detector = ts2_detector = TSBurstDetector(
            set_data        = TS2_SET_DATA,
            first_word_ctrl = 0b1111,
            sets_in_burst   = 8
        )
        m.d.comb += [
            ts2_detector.sink  .stream_eq(self.sink, omit={"ready"}),
            self.ts2_detected  .eq(ts2_detector.detected)
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
            transmit_burst_length = 16
        )
        with m.If(self.send_ts2_burst):
            m.d.comb += [
                ts2_generator.start   .eq(1),
                self.source           .stream_eq(ts2_generator.source)
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
