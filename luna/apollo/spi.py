#
# This file is part of LUNA.
#

# Vendor requests.
REQUEST_DEBUG_SPI_SEND          = 0x50
REQUEST_DEBUG_SPI_READ_RESPONSE = 0x51


class DebugSPIConnection:
    """ Connection to the FPGA via Apollo's Debug SPI. """

    def __init__(self, debugger):
        self._debugger = debugger


    def transfer(self, data_to_send):
        """ Transfers a set of data over SPI, and reads the response. """

        # Transfer the data to be sent...
        self._debugger.out_request(REQUEST_DEBUG_SPI_SEND, data=data_to_send)

        # ... and read the response.
        return self._debugger.in_request(REQUEST_DEBUG_SPI_READ_RESPONSE, length=len(data_to_send))


