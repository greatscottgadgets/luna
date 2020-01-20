#
# This file is part of LUNA.
#

import usb.core

from .jtag  import JTAGChain
from .flash import ConfigurationFlash
from .spi   import DebugSPIConnection
from .ila   import ApolloILAFrontend

class DebuggerNotFound(IOError):
    pass


def create_ila_frontend(ila, *, use_cs_multiplexing=False):
    """ Convenience method that instantiates an Apollo debug session and creates an ILA frontend from it.

    Parameters:
        ila -- The SyncSerialILA object we'll be connecting to.
    """
    debugger = ApolloDebugger()
    return ApolloILAFrontend(debugger, ila=ila)



class ApolloDebugger:
    """ Class representing a link to an Apollo Debug Module. """

    # This VID/PID pair is unique to development LUNA boards.
    # TODO: potentially change this to an OpenMoko VID, like other LUNA boards.
    VENDOR_ID  = 0x16d0
    PRODUCT_ID = 0x05a5

    REQUEST_SET_LED_PATTERN = 0xa1
    REQUEST_RECONFIGURE     = 0xc0

    LED_PATTERN_IDLE = 500
    LED_PATTERN_UPLOAD = 50

    def __init__(self):
        """ Sets up a connection to the debugger. """

        # Try to create a connection to our Apollo debug firmware.
        device = usb.core.find(idVendor=self.VENDOR_ID, idProduct=self.PRODUCT_ID)
        if device is None:
            raise DebuggerNotFound()

        self.device = device

        # Create our basic interfaces, for debugging convenience.
        self.jtag  = JTAGChain(self)
        self.spi   = DebugSPIConnection(self)
        self.flash = ConfigurationFlash(self)


    def out_request(self, number, value=0, index=0, data=None, timeout=5000):
        """ Helper that issues an OUT control request to the debugger. """

        request_type = usb.ENDPOINT_OUT | usb.RECIP_DEVICE | usb.TYPE_VENDOR
        return self.device.ctrl_transfer(request_type, number, value, index, data, timeout=timeout)


    def in_request(self, number, value=0, index=0, length=0, timeout=500):
        """ Helper that issues an IN control request to the debugger. """

        request_type = usb.ENDPOINT_IN | usb.RECIP_DEVICE | usb.TYPE_VENDOR
        result = self.device.ctrl_transfer(request_type, number, value, index, length, timeout=timeout)

        return bytes(result)


    def set_led_pattern(self, number):
        self.out_request(self.REQUEST_SET_LED_PATTERN, number)


    def soft_reset(self):
        """ Resets the target (FPGA/etc) connected to the debug controller. """
        try:
            self.out_request(self.REQUEST_RECONFIGURE)
        except usb.core.USBError:
            pass
