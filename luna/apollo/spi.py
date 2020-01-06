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

        self.command_bytes  = None
        self.register_bytes = None


    def transfer(self, data_to_send):
        """ Transfers a set of data over SPI, and reads the response. """

        # Transfer the data to be sent...
        self._debugger.out_request(REQUEST_DEBUG_SPI_SEND, data=data_to_send)

        # ... and read the response.
        return self._debugger.in_request(REQUEST_DEBUG_SPI_READ_RESPONSE, length=len(data_to_send))



    def _autodetect_command_shape(self):

        # Send out a chain of 16 zeroes, and see what we get back.
        autodetect_value = int.from_bytes(self.transfer(b"\x00" * 16), byteorder="big")

        # Get the start of the transaction; e.g. the sequence of zeroes followed by the sequence of ones.
        autodetect_bits  = "{:0128b}".format(autodetect_value).rstrip('0')
        
        # The leftover number of 0's is our command size in bits; the address size is one less than that.
        # The leftover number of 1's is our register size in bits.
        self.command_bytes  = autodetect_bits.count('0') // 8
        self.register_bytes = autodetect_bits.count('1') // 8


    def register_transaction(self, address, *, is_write, value=0):
        """ Performs an SPI register transaction. """

        if (self.command_bytes is None) or (self.register_bytes is None):
            self._autodetect_command_shape()

        # Compute our write flag.
        write_flag_position = (self.command_bytes * 8) - 1
        write_flag          = (1 << write_flag_position) if is_write else 0

        # Compute our command and value words.
        command = (write_flag | address).to_bytes(self.command_bytes, byteorder='big')
        value   = value.to_bytes(self.register_bytes, byteorder='big')

        # Finally, issue our transaction...
        raw_response = self.transfer(command + value)

        # ... and convert the response back into an integer.
        raw_value = raw_response[self.command_bytes:]
        return int.from_bytes(raw_value, byteorder='big')


    def register_read(self, address):
        """ Reads a value from the provided registers."""
        return self.register_transaction(address, is_write=False)

    def register_write(self, address, value):
        """ Writes a value to the provided register. """
        return self.register_transaction(address, value=value, is_write=True)
