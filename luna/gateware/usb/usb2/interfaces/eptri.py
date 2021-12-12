#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Implementation of a Triple-FIFO endpoint manager.

Equivalent (but not binary-compatbile) implementation of ValentyUSB's ``eptri``.

For an example, see ``examples/usb/eptri`` or TinyUSB's ``luna/dcd_eptri.c``.
"""

from amaranth           import *
from amaranth.lib.fifo  import SyncFIFOBuffered
from amaranth.hdl.xfrm  import ResetInserter, DomainRenamer


from ..endpoint         import EndpointInterface
from ....soc.peripheral import Peripheral
from luna.gateware.usb.usb2 import endpoint


class SetupFIFOInterface(Peripheral, Elaboratable):
    """ Setup component of our `eptri`-equivalent interface.

    Implements the USB Setup FIFO, which handles SETUP packets on any endpoint.

    This interface is similar to an :class:`OutFIFOInterface`, but always ACKs packets,
    and does not allow for any flow control; as a USB device must always be ready to accept
    control packets. [USB2.0: 8.6.1]

    Attributes
    -----

    interface: EndpointInterface
        Our primary interface to the core USB device hardware.
    """

    def __init__(self):
        super().__init__()

        #
        # Registers
        #

        regs = self.csr_bank()

        self.data = regs.csr(8, "r", desc="""
            A FIFO that returns the bytes from the most recently captured SETUP packet.
            Reading a byte from this register advances the FIFO. The first eight bytes read
            from this conain the core SETUP packet.
        """)

        self.reset = regs.csr(1, "w", desc="""
            Local reset control for the SETUP handler; writing a '1' to this register clears the handler state.
        """)

        self.epno = regs.csr(4, "r", desc="The number of the endpoint associated with the current SETUP packet.")
        self.have = regs.csr(1, "r", desc="`1` iff data is available in the FIFO.")
        self.pend = regs.csr(1, "r", desc="`1` iff an interrupt is pending")


        # TODO: figure out where this should actually go to match ValentyUSB as much as possible
        self._address = regs.csr(8, "rw", desc="""
            Controls the current device's USB address. Should be written after a SET_ADDRESS request is
            received. Automatically resets back to zero on a USB reset.
        """)

        #
        # IRQ / Events
        #
        self.setup_received = self.event(desc="""
            Interrupt that triggers when a new SETUP packet is ready to be read.
        """)

        #
        # I/O port
        #
        self.interface = EndpointInterface()

        #
        # Internals
        #

        # Act as a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus
        self.irq        = self._bridge.irq


    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        # Shortcuts to our components.
        interface      = self.interface
        token          = self.interface.tokenizer
        rx             = self.interface.rx
        handshakes_out = self.interface.handshakes_out

        # Logic condition for getting a new setup packet.
        new_setup       = token.new_token & token.is_setup
        reset_requested = self.reset.w_stb & self.reset.w_data
        clear_fifo      = new_setup | reset_requested

        #
        # Core FIFO.
        #
        m.submodules.fifo = fifo = ResetInserter(clear_fifo)(SyncFIFOBuffered(width=8, depth=8))

        m.d.comb += [

            # We'll write to the active FIFO whenever the last received token is a SETUP
            # token, and we have incoming data; and we'll always write the data received
            fifo.w_en                .eq(token.is_setup & rx.valid & rx.next),
            fifo.w_data              .eq(rx.payload),

            # We'll advance the FIFO whenever our CPU reads from the data CSR;
            # and we'll always read our data from the FIFO.
            fifo.r_en                .eq(self.data.r_stb),
            self.data.r_data         .eq(fifo.r_data),

            # Pass the FIFO status on to our CPU.
            self.have.r_data         .eq(fifo.r_rdy),

            # Always acknowledge SETUP packets as they arrive.
            handshakes_out.ack       .eq(token.is_setup & interface.rx_ready_for_response),

            # Trigger a SETUP interrupt as we ACK the setup packet, since that's also the point
            # where we know we're done receiving data.
            self.setup_received.stb  .eq(handshakes_out.ack)
        ]

        #
        # Control registers
        #

        # Our address register always reads the current address of the device;
        # but will generate a
        m.d.comb += self._address.r_data.eq(interface.active_address)
        with m.If(self._address.w_stb):
            m.d.comb += [
                interface.address_changed  .eq(1),
                interface.new_address      .eq(self._address.w_data),
            ]


        #
        # Status and interrupts.
        #

        with m.If(token.new_token):
            m.d.usb += self.epno.r_data.eq(token.endpoint)

        # TODO: generate interrupts

        return DomainRenamer({"sync": "usb"})(m)



class InFIFOInterface(Peripheral, Elaboratable):
    """ IN component of our `eptri`-equivalent interface.

    Implements the FIFO that handles `eptri` IN requests. This FIFO collects USB data, and
    transmits it in response to an IN token. Like all `eptri` interfaces; it can handle only one
    pending packet at a time.


    Attributes
    -----

    interface: EndpointInterface
        Our primary interface to the core USB device hardware.

    """


    def __init__(self, max_packet_size=512):
        """
        Parameters
        ----------
            max_packet_size: int, optional
                Sets the maximum packet size that can be transmitted on this endpoint.
                This should match the value provided in the relevant endpoint descriptor.
        """

        super().__init__()

        self._max_packet_size = max_packet_size

        #
        # Registers
        #

        regs = self.csr_bank()

        self.data = regs.csr(8, "w", desc="""
            Write-only register. Each write enqueues a byte to be transmitted; gradually building
            a single packet to be transmitted. This queue should only ever contain a single packet;
            it is the software's responsibility to handle breaking requests down into packets.
        """)

        self.epno = regs.csr(4, "rw", desc="""
            Contains the endpoint the enqueued packet is to be transmitted on. Writing this register
            marks the relevant packet as ready to transmit; and thus should only be written after a
            full packet has been written into the FIFO. If no data has been placed into the DATA FIFO,
            a zero-length packet is generated.

            Note that any IN requests that do not match the endpoint number are automatically NAK'd.
        """)

        self.reset = regs.csr(1, "w", desc="A write to this register clears the FIFO without transmitting.")

        self.stall = regs.csr(1, "rw", desc="""
            When this register contains '1', any IN tokens targeting `epno` will be responded to with a
            STALL token, rather than DATA or a NAK.

            For EP0, this register will automatically be cleared when a new SETUP token is received.
        """)

        self.idle = regs.csr(1, "r", desc="This value is `1` if no packet is actively being transmitted.")
        self.have = regs.csr(1, "r", desc="This value is `1` if data is present in the transmit FIFO.")
        self.pend = regs.csr(1, "r", desc="`1` iff an interrupt is pending")
        self.pid  = regs.csr(1, "rw", desc="Contains the current PID toggle bit for the given endpoint.")

        #
        # Interrupts
        #

        self._done_irq = self.event(name="done", desc="""
            Indicates that the host has successfully transferred an ``IN`` packet,
            and that the FIFO is now empty.
        """)

        #
        # I/O port
        #
        self.interface = EndpointInterface()

        #
        # Internals
        #

        # Act as a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus
        self.irq        = self._bridge.irq



    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        # Shortcuts to our components.
        token          = self.interface.tokenizer
        tx             = self.interface.tx
        handshakes_out = self.interface.handshakes_out

        #
        # Core FIFO.
        #


        # Create our FIFO; and set it to be cleared whenever the user requests.
        m.submodules.fifo = fifo = ResetInserter(self.reset.w_stb)(
            SyncFIFOBuffered(width=8, depth=self._max_packet_size)
        )

        m.d.comb += [
            # Whenever the user DATA register is written to, add the relevant data to our FIFO.
            fifo.w_en         .eq(self.data.w_stb),
            fifo.w_data       .eq(self.data.w_data),
        ]

        # Keep track of the amount of data in our FIFO.
        bytes_in_fifo = Signal(range(0, self._max_packet_size + 1))

        # If we're clearing the whole FIFO, reset our data count.
        with m.If(self.reset.w_stb):
            m.d.usb += bytes_in_fifo.eq(0)

        # Keep track of our FIFO's data count as data is added or removed.
        increment = fifo.w_en & fifo.w_rdy
        decrement = fifo.r_en & fifo.r_rdy

        with m.Elif(increment & ~decrement):
            m.d.usb += bytes_in_fifo.eq(bytes_in_fifo + 1)
        with m.Elif(decrement & ~increment):
            m.d.usb += bytes_in_fifo.eq(bytes_in_fifo - 1)


        #
        # Register updates.
        #

        # Active endpoint number.
        with m.If(self.epno.w_stb):
            m.d.usb += self.epno.r_data.eq(self.epno.w_data)

        # Keep track of which endpoints are stalled.
        endpoint_stalled  = Array(Signal() for _ in range(16))

        # Keep track of the current DATA pid for each endpoint.
        endpoint_data_pid = Array(Signal() for _ in range(16))

        # Clear our system state on reset.
        with m.If(self.reset.w_stb):
            for i in range(16):
                m.d.usb += [
                    endpoint_stalled[i]   .eq(0),
                    endpoint_data_pid[i]  .eq(0),
                ]


        # Set the value of our endpoint `stall` based on our `stall` register...
        with m.If(self.stall.w_stb):
            m.d.usb += endpoint_stalled[self.epno.r_data].eq(self.stall.w_data)

        # Clear our endpoint `stall` when we get a SETUP packet, and reset the endpoint's
        # data PID to DATA1, as per [USB2.0: 8.5.3], the first packet of the DATA or STATUS
        # phase always carries a DATA1 PID.
        with m.If(token.is_setup & token.new_token):
            m.d.usb += [
                endpoint_stalled[token.endpoint]   .eq(0),
                endpoint_data_pid[token.endpoint]  .eq(1)
            ]


        #
        # Status registers.
        #
        m.d.comb += [
            self.have.r_data  .eq(fifo.r_rdy),
            self.pid.r_data   .eq(endpoint_data_pid[self.epno.r_data])
        ]

        #
        # Data toggle control.
        #
        endpoint_matches = (token.endpoint == self.epno.r_data)
        packet_complete  = self.interface.handshakes_in.ack & token.is_in & endpoint_matches

        # Always drive the DATA pid we're transmitting with our current data pid.
        m.d.comb += self.interface.tx_pid_toggle.eq(endpoint_data_pid[token.endpoint])

        # If our controller is overriding the data PID, accept the override.
        with m.If(self.pid.w_stb):
            m.d.usb += endpoint_data_pid[self.epno.r_data].eq(self.pid.w_data)

        # Otherwise, toggle our expected DATA PID once we receive a complete packet.
        with m.Elif(packet_complete):
            m.d.usb += endpoint_data_pid[token.endpoint].eq(~endpoint_data_pid[token.endpoint])


        #
        # Control logic.
        #

        # Logic shorthand.
        new_in_token     = (token.is_in & token.ready_for_response)
        stalled          = endpoint_stalled[token.endpoint]

        with m.FSM(domain='usb') as f:

            # Drive our IDLE line based on our FSM state.
            m.d.comb += self.idle.r_data.eq(f.ongoing('IDLE'))

            # IDLE -- our CPU hasn't yet requested that we send data.
            # We'll wait for it to do so, and NAK any packets that arrive.
            with m.State("IDLE"):

                # If we get an IN token...
                with m.If(new_in_token):

                    # STALL it, if the endpoint is STALL'd...
                    with m.If(stalled):
                        m.d.comb += handshakes_out.stall.eq(1)

                    # Otherwise, NAK.
                    with m.Else():
                        m.d.comb += handshakes_out.nak.eq(1)


                # If the user request that we send data, "prime" the endpoint.
                # This means we have data to send, but are just waiting for an IN token.
                with m.If(self.epno.w_stb & ~stalled):
                    m.next = "PRIMED"

                # Always return to IDLE on reset.
                with m.If(self.reset.w_stb):
                    m.next = "IDLE"

            # PRIMED -- our CPU has provided data, but we haven't been sent an IN token, yet.
            # Await that IN token.
            with m.State("PRIMED"):

                with m.If(new_in_token):

                    # If the target endpoint is STALL'd, reply with STALL no matter what.
                    with m.If(stalled):
                        m.d.comb += handshakes_out.stall.eq(1)

                    # If we have a new IN token to our endpoint, move to responding to it.
                    with m.Elif(endpoint_matches):

                        # If there's no data in our endpoint, send a ZLP.
                        with m.If(~fifo.r_rdy):
                            m.next = "SEND_ZLP"

                        # Otherwise, send our data, starting with our first byte.
                        with m.Else():
                            m.d.usb += tx.first.eq(1)
                            m.next = "SEND_DATA"

                    # Otherwise, we don't have a response; NAK the packet.
                    with m.Else():
                        m.d.comb += handshakes_out.nak.eq(1)

                # Always return to IDLE on reset.
                with m.If(self.reset.w_stb):
                    m.next = "IDLE"

            # SEND_ZLP -- we're now now ready to respond to an IN token with a ZLP.
            # Send our response.
            with m.State("SEND_ZLP"):
                m.d.comb += [
                    tx.valid  .eq(1),
                    tx.last   .eq(1)
                ]
                m.d.comb += self._done_irq.stb.eq(1)
                m.next = 'IDLE'

            # SEND_DATA -- we're now ready to respond to an IN token to our endpoint.
            # Send our response.
            with m.State("SEND_DATA"):
                last_byte = (bytes_in_fifo == 1)

                m.d.comb += [
                    tx.valid    .eq(1),
                    tx.last     .eq(last_byte),

                    # Drive our transmit data directly from our FIFO...
                    tx.payload  .eq(fifo.r_data),

                    # ... and advance our FIFO each time a data byte is transmitted.
                    fifo.r_en   .eq(tx.ready)
                ]

                # After we've sent a byte, drop our first flag.
                with m.If(tx.ready):
                    m.d.usb += tx.first.eq(0)

                # Once we transmit our last packet, we're done transmitting. Move back to IDLE.
                with m.If(last_byte & tx.ready):
                    # Trigger our DONE interrupt.
                    m.d.comb += self._done_irq.stb.eq(1)
                    m.next = 'IDLE'

                # Always return to IDLE on reset.
                with m.If(self.reset.w_stb):
                    m.next = "IDLE"

        return DomainRenamer({"sync": "usb"})(m)



class OutFIFOInterface(Peripheral, Elaboratable):
    """ OUT component of our `eptri`

    Implements the OUT FIFO, which handles receiving packets from our host.

    Attributes
    -----

    interface: EndpointInterface
        Our primary interface to the core USB device hardware.
    """

    def __init__(self, max_packet_size=512):
        super().__init__()

        self._max_packet_size = max_packet_size

        #
        # Registers
        #

        regs = self.csr_bank()
        self.data = regs.csr(8, "r", desc="""
            A FIFO that returns the bytes from the most recently captured OUT transaction.
            Reading a byte from this register advances the FIFO.
        """)
        self.data_ep = regs.csr(4, "r", desc="""
            Register that contains the endpoint number associated with the data in the FIFO -- that is,
            the endpoint number on which the relevant data was received.
        """)

        self.reset = regs.csr(1, "w", desc="""
            Local reset for the OUT handler; clears the out FIFO.
        """)

        self.epno = regs.csr(4, "rw", desc="""
            Selects the endpoint number to prime. This interface only allows priming a single endpoint at once--
            that is, only one endpoint can be ready to receive data at a time. See the `enable` bit for usage.
        """)

        self.enable = regs.csr(1, "rw", desc="""
            Controls whether any data can be received on any primed OUT endpoint. This bit is automatically cleared
            on receive in order to give the controller time to read data from the FIFO. It must be re-enabled once
            the FIFO has been emptied.
        """)

        self.prime = regs.csr(1, "w", desc="""
            Controls "priming" an out endpoint. To receive data on any endpoint, the CPU must first select
            the endpoint with the `epno` register; and then write a '1' into the prime and enable register.
            This prepares our FIFO to receive data; and the next OUT transaction will be captured into the FIFO.

            When a transaction is complete, the `enable` bit is reset; the `prime` is not. This effectively means
            that `enable` controls receiving on _any_ of the primed endpoints; while `prime` can be used to build
            a collection of endpoints willing to participate in receipt.

            Only one transaction / data packet is captured per `enable` write; repeated enabling is necessary
            to capture multiple packets.
        """)

        self.stall = regs.csr(1, "rw", desc="""
            Controls STALL'ing the active endpoint. Setting or clearing this bit will set or clear STALL on
            the provided endpoint. Endpoint STALLs persist even after `epno` is changed; so multiple endpoints
            can be stalled at once by writing their respective endpoint numbers into `epno` register and then
            setting their `stall` bits.
        """)


        self.have = regs.csr(1, "r", desc="`1` iff data is available in the FIFO.")
        self.pend = regs.csr(1, "r", desc="`1` iff an interrupt is pending")

        # TODO: figure out where this should actually go to match ValentyUSB as much as possible
        self._address = regs.csr(8, "rw", desc="""
            Controls the current device's USB address. Should be written after a SET_ADDRESS request is
            received. Automatically resets back to zero on a USB reset.
        """)

        self.pid  = regs.csr(1, "rw", desc="Contains the current PID toggle bit for the given endpoint.")

        #
        # Interrupts.
        #

        self._done_irq = self.event(name="done", desc="""
            Indicates that an ``OUT`` packet has successfully been transferred
            from the host.  This bit must be cleared in order to receive
            additional packets.
        """)


        #
        # I/O port
        #
        self.interface = EndpointInterface()

        #
        # Internals
        #

        # Act as a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus
        self.irq        = self._bridge.irq


    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        # Shortcuts to our components.
        interface      = self.interface
        token          = self.interface.tokenizer
        rx             = self.interface.rx
        handshakes_out = self.interface.handshakes_out

        #
        # Control registers
        #

        # Active endpoint number.
        with m.If(self.epno.w_stb):
            m.d.usb += self.epno.r_data.eq(self.epno.w_data)

        # Keep track of which endpoints are primed.
        endpoint_primed   = Array(Signal() for _ in range(16))

        # Keep track of which endpoints are stalled.
        endpoint_stalled  = Array(Signal() for _ in range(16))

        # Keep track of the PIDs for each endpoint, which we'll toggle automatically.
        endpoint_data_pid = Array(Signal() for _ in range(16))

        # Keep track of whether we're enabled.
        with m.If(self.enable.w_stb):
            m.d.usb += self.enable.r_data.eq(self.enable.w_data)

        # If Prime is written to, mark the relevant endpoint as primed.
        with m.If(self.prime.w_stb):
            m.d.usb += endpoint_primed[self.epno.r_data].eq(self.prime.w_data)

        # If we've just ACK'd a receive, clear our enable and un-prime the given endpoint.
        with m.If(interface.handshakes_out.ack & token.is_out):
            m.d.usb += [
                self.enable.r_data                .eq(0),
                endpoint_primed[token.endpoint]   .eq(0),
            ]

        # Set the value of our endpoint `stall` based on our `stall` register...
        with m.If(self.stall.w_stb):
            m.d.usb += endpoint_stalled[self.epno.r_data].eq(self.stall.w_data)

        # Allow our controller to override our DATA pid, selectively.
        with m.If(self.pid.w_stb):
            m.d.usb += endpoint_data_pid[self.epno.r_data].eq(self.pid.w_data)

        # Clear our endpoint `stall` when we get a SETUP packet, and reset the endpoint's
        # data PID to DATA1, as per [USB2.0: 8.5.3], the first packet of the DATA or STATUS
        # phase always carries a DATA1 PID.
        with m.If(token.is_setup & token.new_token):
            m.d.usb += [
                endpoint_stalled[token.endpoint]   .eq(0),
                endpoint_data_pid[token.endpoint]  .eq(1)
            ]

        #
        # Core FIFO.
        #
        m.submodules.fifo = fifo = ResetInserter(self.reset.w_stb)(
            SyncFIFOBuffered(width=8, depth=self._max_packet_size)
        )

        # Shortcut for when we should allow a receive. We'll read when:
        #  - Our `epno` register matches the target register; and
        #  - We've primed the relevant endpoint.
        #  - Our most recent token is an OUT.
        #  - We're not stalled.
        stalled          = token.is_out & endpoint_stalled[token.endpoint]
        endpoint_primed  = endpoint_primed[token.endpoint]
        ready_to_receive = endpoint_primed & self.enable.r_data & ~stalled
        allow_receive    = token.is_out & ready_to_receive
        nak_receives     = token.is_out & ~ready_to_receive & ~stalled

        # Shortcut for when we have a "redundant"/incorrect PID. In these cases, we'll assume
        # the host missed our ACK, and per the USB spec, implicitly ACK the packet.
        is_redundant_pid    = (interface.rx_pid_toggle != endpoint_data_pid[token.endpoint])
        is_redundant_packet = endpoint_primed & token.is_out & is_redundant_pid

        # Shortcut conditions under which we'll ACK and NAK a receive.
        ack_redundant_packet = (is_redundant_packet & interface.rx_ready_for_response)
        ack_receive          = allow_receive & interface.rx_ready_for_response
        nak_receive          = nak_receives  & interface.rx_ready_for_response & ~ack_redundant_packet

        # Conditions under which we'll ACK or NAK a ping.
        ack_ping         = ready_to_receive  & token.is_ping & token.ready_for_response
        nak_ping         = ~ready_to_receive & token.is_ping & token.ready_for_response

        m.d.comb += [
            # We'll write to the endpoint iff we've valid data, and we're allowed receive.
            fifo.w_en         .eq(allow_receive & rx.valid & rx.next & ~is_redundant_packet),
            fifo.w_data       .eq(rx.payload),

            # We'll advance the FIFO whenever our CPU reads from the data CSR;
            # and we'll always read our data from the FIFO.
            fifo.r_en         .eq(self.data.r_stb),
            self.data.r_data  .eq(fifo.r_data),

            # Pass the FIFO status on to our CPU.
            self.have.r_data  .eq(fifo.r_rdy),

            # If we've just finished an allowed receive, ACK.
            handshakes_out.ack    .eq(ack_receive | ack_ping | ack_redundant_packet),

            # Trigger our DONE interrupt once we ACK a received/allowed packet.
            self._done_irq.stb    .eq(ack_receive),

            # If we were stalled, stall.
            handshakes_out.stall  .eq(stalled & interface.rx_ready_for_response),

            # If we're not ACK'ing or STALL'ing, NAK all packets.
            handshakes_out.nak    .eq(nak_receive | nak_ping),

            # Always indicate the current DATA PID in the PID register.
            self.pid.r_data       .eq(endpoint_data_pid[self.epno.r_data])
        ]

        # Whenever we capture data, update our associated endpoint number
        # to match the endpoint on which we received the relevant data.
        with m.If(fifo.w_en):
            m.d.usb += self.data_ep.r_data.eq(token.endpoint)

        # Whenever we ACK a non-redundant receive, toggle our DATA PID.
        # (unless the user happens to be overriding it by writing to the PID register).
        with m.If(ack_receive & ~is_redundant_packet & ~self.pid.w_stb):
            m.d.usb += endpoint_data_pid[token.endpoint].eq(~endpoint_data_pid[token.endpoint])


        #
        # Interrupt/status
        #

        return DomainRenamer({"sync": "usb"})(m)
