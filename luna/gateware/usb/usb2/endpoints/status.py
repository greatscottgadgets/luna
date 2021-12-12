#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Endpoint interfaces for providing status updates to the host.

These are mainly meant for use with interrupt endpoints; and allow a host to e.g.
repeatedly poll a device for status.
"""

from amaranth       import Elaboratable, Module, Signal, Array

from ..endpoint     import EndpointInterface
from ....utils.cdc  import synchronize


class USBSignalInEndpoint(Elaboratable):
    """ Endpoint that transmits the value of a signal to a host whenever polled.

    This is intended to be usable to implement a simple interrupt endpoint that polls for a status signal.

    Attributes
    ----------
    signal: Signal(<variable width>), input
        The signal to be relayed to the host. This signal's current value will be relayed each time the
        host polls our endpoint.
    interface: EndpointInterface
        Communications link to our USB device.

    status_read_complete: Signal(), output
        Strobe that pulses high for a single `usb`-domain cycle each time a status read is complete.

    Parameters
    ----------
    width: int
        The width of the signal we'll relay up to the host, in bits.
    endpoint_number: int
        The endpoint number (not address) this endpoint should respond to.
    endianness: str, "big" or "little", optional
        The endianness with which to send the data. Defaults to little endian.
    signal_domain: str, optional
        The name of the domain :attr:``signal`` is clocked from. If this value is anything other than
        "usb", the signal will automatically be synchronized to the USB clock domain.
    """

    def __init__(self, *, width, endpoint_number, endianness="little", signal_domain="usb"):
        self._width           = width
        self._endpoint_number = endpoint_number
        self._signal_domain   = signal_domain
        self._endianness      = endianness

        if self._endianness not in ("big", "little"):
            raise ValueError(f"Endianness must be 'big' or 'little', not {endianness}.")

        #
        # I/O port
        #
        self.signal               = Signal(self._width)
        self.interface            = EndpointInterface()

        self.status_read_complete = Signal()



    def elaborate(self, platform):
        m = Module()

        # Shortcuts.
        tx = self.interface.tx
        tokenizer = self.interface.tokenizer


        # Grab a copy of the relevant signal that's in our USB domain; synchronizing if we need to.
        if self._signal_domain == "usb":
            target_signal = self.signal
        else:
            target_signal = synchronize(m, self.signal, o_domain="usb")


        # Store a latched version of our signal, captured before we start a transmission.
        latched_signal = Signal.like(self.signal)

        # Grab an byte-indexable reference into our signal.
        bytes_in_signal = (self._width + 7) // 8
        signal_bytes = Array(latched_signal[n * 8 : n * 8 + 8] for n in range(bytes_in_signal))

        # Store how many bytes we've transmitted.
        bytes_transmitted = Signal(range(0, bytes_in_signal + 1))

        #
        # Data transmission logic.
        #

        # If this signal is big endian, send them in reading order; otherwise, index our multiplexer in reverse.
        # Note that our signal is captured little endian by default, due the way we use Array() above. If we want
        # big endian; then we'll flip it.
        if self._endianness == "little":
            index_to_transmit = bytes_transmitted
        else:
            index_to_transmit = bytes_in_signal - bytes_transmitted - 1

        # Always transmit the part of the latched signal byte that corresponds to our
        m.d.comb += tx.payload.eq(signal_bytes[index_to_transmit])

        #
        # Core control FSM.
        #

        endpoint_number_matches  = (tokenizer.endpoint == self._endpoint_number)
        targeting_endpoint       = endpoint_number_matches & tokenizer.is_in
        packet_requested         = targeting_endpoint & tokenizer.ready_for_response


        with m.FSM(domain="usb"):

            # IDLE -- we've not yet gotten an token requesting data. Wait for one.
            with m.State('IDLE'):

                # Once we're ready to send a response...
                with m.If(packet_requested):

                    m.d.usb += [
                        # ... clear our transmit counter ...
                        bytes_transmitted  .eq(0),

                        # ... latch in our response...
                        latched_signal     .eq(self.signal),
                    ]

                    # ...  and start transmitting it.
                    m.next = "TRANSMIT_RESPONSE"


            # TRANSMIT_RESPONSE -- we're now ready to send our latched response to the host.
            with m.State("TRANSMIT_RESPONSE"):
                is_last_byte = bytes_transmitted + 1 == bytes_in_signal

                # While we're transmitting, our Tx data is valid.
                m.d.comb += [
                    tx.valid  .eq(1),
                    tx.first  .eq(bytes_transmitted == 0),
                    tx.last   .eq(is_last_byte)
                ]

                # Each time we receive a byte, move on to the next one.
                with m.If(tx.ready):
                    m.d.usb += bytes_transmitted.eq(bytes_transmitted + 1)

                    # If this is the last byte to be transmitted, move to waiting for an ACK.
                    with m.If(is_last_byte):
                        m.next = "WAIT_FOR_ACK"


            # WAIT_FOR_ACK -- we've now transmitted our full packet; we need to wait for the host to ACK it
            with m.State("WAIT_FOR_ACK"):

                # If the host does ACK, we're done! Move back to our idle state.
                with m.If(self.interface.handshakes_in.ack):
                    m.d.comb += self.status_read_complete.eq(1)
                    m.d.usb += self.interface.tx_pid_toggle[0].eq(~self.interface.tx_pid_toggle[0])
                    m.next = "IDLE"


                # If the host starts a new packet without ACK'ing, we'll need to retransmit.
                # Wait for a new IN token.
                with m.If(self.interface.tokenizer.new_token):
                    m.next = "RETRANSMIT"


            # RETRANSMIT -- the host failed to ACK the data we've most recently sent.
            # Wait here for the host to request the data again.
            with m.State("RETRANSMIT"):

                # Once the host does request the data again...
                with m.If(packet_requested):

                    # ... retransmit it, starting from the beginning.
                    m.d.usb += bytes_transmitted.eq(0),
                    m.next = "TRANSMIT_RESPONSE"

        return m


