#
# This file is part of LUNA.
#

import time

# Vendor requests.
REQUEST_TAKE_CONFIG_LINES       = 0x53
REQUEST_RELEASE_CONFIG_LINES    = 0x54

REQUEST_FLASH_SPI_SEND          = 0x52
REQUEST_FLASH_SPI_READ_RESPONSE = 0x51


class ConfigurationFlash:
    """
    Class representing a connection to an FPGA configuration flash. 
    Supports only the flashes used with LUNA boards; rather than being a general-case flasher.
    """

    # How long we should wait between attempts to poll for status.
    # You may want to set this to an arbitrary low number; as this will essentially just
    # yield to the system scheduler.
    POLL_INTERVAL     = 0.001

    # The amount of time we'll need to wait after each page program. Performing this wait
    # directly here saves us from having to poll.
    PAGE_PROGRAM_TIME = 0.003

    # List of flash ID pairs for flash chips used on LUNA boards.
    FLASH_DESCRIPTIONS = {
        0xef15: "Winbond W25Q32JV (32Mbit)"
    }

    # Page size to use for all relevant commands.
    PAGE_SIZE = 256

    # Flash command constants.
    # These are currently supported on all flash parts used on all LUNA boards.
    COMMAND_PAGE_PROGRAM = 0x02
    COMMAND_READ_DATA    = 0x03
    COMMAND_READ_STATUS  = 0x05
    COMMAND_WRITE_ENABLE = 0x06
    COMMAND_FULL_ERASE   = 0x60
    COMMAND_READ_ID      = 0x90


    # Status register masks.
    STATUS_BUSY_MASK   = (1 << 0)
    STATUS_WRITE_MASK  = (1 << 1)


    def __init__(self, debugger):
        """ Params:
            debugger -- The apollo debugger instance to work with.
        """
        self._debugger = debugger


    def initialize(self):
        """ 
        Starts a persistent connection to the relevant SPI flash.
        When possible, prefer using `with <object>` instead.
        """
        self.__enter__()


    def __enter__(self):
        """ Starts an SPI-flash session, taking control of the configuration lines. """
        self._debugger.out_request(REQUEST_TAKE_CONFIG_LINES)
        return self


    def __exit__(self, item_type, value, tb):
        """ Places the device into a safe stopping state, and then releases access to it. """
        self._disable_write_access()
        self._debugger.out_request(REQUEST_RELEASE_CONFIG_LINES)


    def _transfer(self, data_to_send):
        """ Transfers a set of data over SPI, and reads the response. """

        # Transfer the data to be sent...
        self._debugger.out_request(REQUEST_FLASH_SPI_SEND, data=data_to_send)

        # ... and read the response.
        return self._debugger.in_request(REQUEST_FLASH_SPI_READ_RESPONSE, length=len(data_to_send))


    def _simple_instruction(self, instruction, *, response_length=0, padding_bytes=0):
        """ Performs a simple flash instruction and returns the result. """

        # Build a command from the instruction and any bytes that should follow it.
        trailing_bytes = padding_bytes + response_length
        command = bytes([instruction] + ([0] * trailing_bytes))

        # Issue the command, and extract the response.
        response = self._transfer(command)
        return response[padding_bytes + 1:]


    def read_flash_id(self):
        """ Reads the ID from the attached flash chip and returns it. """
        return self._simple_instruction(self.COMMAND_READ_ID, padding_bytes=3, response_length=2)


    def read_flash_info(self):
        """ Reads the flash ID from the attached chip.

        Returns: 
            flash_id    -- A 16-bit number identifying the target flash
            description -- A string describing the flash chip
        """

        raw_flash_id = self.read_flash_id()
        flash_id     = int.from_bytes(raw_flash_id, byteorder='big')

        if flash_id in [0x0000, 0xFFFF]:
            return None, "No flash detected."

        elif flash_id in self.FLASH_DESCRIPTIONS:
            return flash_id, self.FLASH_DESCRIPTIONS[flash_id]

        else:
            return flash_id, "Unknown flash chip."


    def _read_status_register(self):
        """ Reads the contents of the flash chip's status register. """

        status = self._simple_instruction(self.COMMAND_READ_STATUS, response_length=1)
        return int.from_bytes(status, byteorder='big')


    def _enable_write_access(self):
        """ Enables write access to the relevant flash. """
        self._simple_instruction(self.COMMAND_WRITE_ENABLE)


    def _disable_write_access(self):
        """ Disables write access to the given flash. """
        self._simple_instruction(self.COMMAND_WRITE_ENABLE)


    def _wait_for_completion(self):
        """ Waits for the device to complete the started write or erase command. """

        # Spin until the busy 
        while (self._read_status_register() & self.STATUS_BUSY_MASK):
            time.sleep(self.POLL_INTERVAL)


    def erase(self):
        """ Erases the target configuration flash. """

        # Ensure we have write access to the relevant flash.
        self._enable_write_access()
        assert(self._read_status_register() & self.STATUS_WRITE_MASK)

        # Perform the chip-erase command
        self._simple_instruction(self.COMMAND_FULL_ERASE)

        # Wait for the operation to complete.
        self._wait_for_completion()


    def _program_page(self, address, data):
        """ Programs a page of the relevant SPI flash. """

        # Re-enable write access, as it's disabled after each page program.
        self._enable_write_access()

        # Build our data stream:
        # 1. our command
        data_out = bytearray()
        data_out.append(self.COMMAND_PAGE_PROGRAM)
        
        # 2. the address to write to 
        addr_bytes = address.to_bytes(3, byteorder='big')
        data_out.extend(addr_bytes)

        # 3. the data to be written
        data_out.extend(data)

        # Issue our combined command...
        self._transfer(data_out)

        # ... and wait for it to complete.
        time.sleep(self.PAGE_PROGRAM_TIME)



    def program(self, data_bytes, log_function=lambda _ : None):
        """ Programs the given flash with the relevant data. """

        data = bytearray(data_bytes)

        # Start at the beginning of our flash, and work our way forward.
        to_program      = len(data_bytes)
        current_address = 0

        # First, erase the target flash.
        log_function("Erasing the target flash to prepare for program...")
        self.erase()

        log_function("Programming the target bitstream...")
        while data:

            # Extract the current page of data...
            page = data[0:self.PAGE_SIZE]
            del data[0:self.PAGE_SIZE]

            # ... program it...
            self._program_page(current_address, page)

            # ... and move to the next page.
            current_address += len(page)

        log_function("Programming complete; all bytes written.\n")


    def _read_page(self, address, length):
        """ Reads a single page from the relevant SPI flash. """
        return self._simple_instruction(self.COMMAND_READ_DATA, response_length=length)


    def readback(self, length,  log_function=lambda _ : None):
        """ Reads the provided length back from the SPI configuration flash. """
   
        data = bytearray()
        address = 0
        bytes_remaining = length

        log_function("Reading back configuration flash...")
        while bytes_remaining:
            chunk_size = min(self.PAGE_SIZE, bytes_remaining)
            chunk = self._read_page(address, chunk_size)
            data.extend(chunk)

            address         += len(chunk)
            bytes_remaining -= len(chunk)
            log_function("Read {} of {} bytes.".format(address, length))

        return data
