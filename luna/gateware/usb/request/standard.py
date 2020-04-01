#
# This file is part of LUNA.
#
""" Standard, full-gateware control request handlers. """

from nmigen                 import Module, Elaboratable
from usb_protocol.types     import USBStandardRequests
from usb_protocol.emitters  import DeviceDescriptorCollection

from ..usb2.request         import RequestHandlerInterface
from ..usb2.descriptor      import GetDescriptorHandler

from ...test                import LunaGatewareTestCase, usb_domain_test_case

class StandardRequestHandler(Elaboratable):
    """ Pure-gateware USB setup request handler.

    Work in progress. Not yet working. (!)
    """

    def __init__(self, descriptors: DeviceDescriptorCollection):
        """
        Parameters:
            descriptors    -- The DeviceDescriptorCollection that contains our descriptors.
        """

        self.descriptors = descriptors

        #
        # I/O port
        #
        self.interface = RequestHandlerInterface()


    def send_zlp(self, m):
        """ Requests send of a zero-length packet. Intended to be called from an FSM. """

        tx = self.interface.tx

        # Send a ZLP along our transmit interface.
        # Our interface accepts 'valid' and 'last' without 'first' as a ZLP.
        m.d.comb += [
            tx.valid  .eq(1),
            tx.last   .eq(1)
        ]


    def elaborate(self, platform):
        m = Module()
        interface = self.interface

        # Create convenience aliases for our interface components.
        setup               = interface.setup
        handshake_generator = interface.handshake
        handshake_detected  = interface.handshake_detected
        tx                  = interface.tx


        #
        # Submodules
        #

        m.submodules.get_descriptor = get_descriptor_handler = GetDescriptorHandler(self.descriptors)
        m.d.comb += [
            get_descriptor_handler.value  .eq(setup.value),
            get_descriptor_handler.length .eq(setup.length),
        ]


        #
        # Handlers.
        #

        with m.FSM(domain="usb"):

            # IDLE -- not handling any active request
            with m.State('IDLE'):

                # If we've received a new setup packet, handle it.
                # TODO: limit this to standard requests
                with m.If(setup.received):


                    # Select which standard packet we're going to handler.
                    with m.Switch(setup.request):

                        with m.Case(USBStandardRequests.SET_ADDRESS):
                            m.next = 'SET_ADDRESS'
                        with m.Case(USBStandardRequests.GET_DESCRIPTOR):
                            m.next = 'GET_DESCRIPTOR'
                        with m.Case():
                            m.next = 'UNHANDLED'


            # SET_ADDRESS -- The host is trying to assign us an address.
            with m.State('SET_ADDRESS'):

                with m.If(interface.status_requested):
                    self.send_zlp(m)

                with m.If(handshake_detected.ack):
                    m.d.comb += [
                        interface.address_changed  .eq(1),
                        interface.new_address      .eq(setup.value[0:7])
                    ]

                    m.next = 'IDLE'


            # GET_DESCRIPTOR -- The host is asking for a USB descriptor -- for us to "self describe".
            with m.State('GET_DESCRIPTOR'):
                m.d.comb += [
                    get_descriptor_handler.tx  .attach(interface.tx),
                    handshake_generator.stall  .eq(get_descriptor_handler.stall)
                ]

                # Respond to our data stage with a descriptor...
                with m.If(interface.data_requested):
                    m.d.comb += get_descriptor_handler.start  .eq(1),

                # ... and ACK our status stage.
                with m.If(interface.status_requested):
                    m.d.comb += handshake_generator.ack.eq(1)
                    m.next = 'IDLE'


            # UNHANDLED -- we've received a request we're not prepared to handle
            with m.State('UNHANDLED'):

                # When we next have an opportunity to stall, do so,
                # and then return to idle.
                with m.If(interface.data_requested | interface.status_requested):
                    m.d.comb += handshake_generator.stall.eq(1)
                    m.next = 'IDLE'

        return m


class StandardRequestHandlerTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = None
    USB_CLOCK_FREQUENCY  = 60e6

    FRAGMENT_UNDER_TEST = StandardRequestHandler

    @usb_domain_test_case
    def test_set_address(self):
        yield




if __name__ == "__main__":
    unittest.main(warnings="ignore")
