#
# This file is part of LUNA.
#

import usb.core

class DebuggerNotFound(IOError):
    pass


class ApolloDebugger:
    """ Class representing a link to an Apollo Debug Module. """

    # FIXME: replace these with newly allocated openmoko IDs?
    VENDOR_ID  = 0x1d50
    PRODUCT_ID = 0x60e7

    REQUEST_SET_LED_PATTERN = 0xa1

    LED_PATTERN_IDLE = 500
    LED_PATTERN_UPLOAD = 50

    def __init__(self):
        """ Sets up a connection to the debugger. """

        # Try to create a connection to our Apollo debug firmware.
        device = usb.core.find(idVendor=self.VENDOR_ID, idProduct=self.PRODUCT_ID)
        if device is None:
            raise DebuggerNotFound()

        self.device = device


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
