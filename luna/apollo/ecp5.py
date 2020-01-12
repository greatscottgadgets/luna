#
# This file is part of LUNA
#
""" ECP5 configuration code for LUNA. """

import time

from enum import IntEnum
from collections import defaultdict

from .jtag import JTAGChain
from .support.bits import bits


class ECP5Programmer:
    """ Abstract base class for programming ECP5 FPGAs. """

    # Part names for various ECP5 part IDs.
    # Possibly missing a 12F variant of the 5UM. Definitely missing -5G part names.
    # TODO: grab all of the names from Trellis?
    PART_NAMES = {
        0x21111043: 'LFE5U-12',
        0x41111043: 'LFE5U-25',
        0x41112043: 'LFE5U-45',
        0x41113043: 'LFE5U-85',

        0x01111043: 'LFE5UM-25',
        0x01112043: 'LFE5UM-45',
        0x01113043: 'LFE5UM-25',
    }

    #
    # Status register components.
    #

    # JTAG mode is active.
    STATUS_FLAG_JTAG_ACTIVE = (1 << 4)

    # Configuration logic is busy.
    STATUS_FLAG_BUSY   = (1 << 12)

    # Last command failed.
    STATUS_FLAG_FAIL   = (1 << 13)

    # Done bit has been set.
    STATUS_FLAG_DONE   = (1 << 8)

    # Mismatch with VERIFY_ID command.
    STATUS_FLAG_ID_ERROR        = (1 << 27)

    # Invalid command detected, or execution failed.
    STATUS_FLAG_INVALID_COMMAND = (1 << 28)
    STATUS_FLAG_EXECUTION_FAIL = (1 << 26)

    # Programming status.
    STATUS_FLAG_ISC_ENABLE      = (1 <<  9)
    STATUS_FLAG_WRITEABLE       = (1 << 10)
    STATUS_FLAG_READABLE        = (1 << 11)
    STATUS_FLAG_STANDARD_PRE    = (1 << 21)

    # A previous SPI flash programming attempt failed.
    STATUS_FLAG_SPI_FAIL = (1 << 22)

    # Error codes.
    STATUS_ERROR_SHIFT = 23
    STATUS_ERROR_MASK  = 0b111
    STATUS_ERROR_CODES = {
        0: 'error unknown',
        1: 'part ID mismatch',
        2: 'illegal command issued',
        3: 'CRC check failed',
        4: 'preamble error',
        5: 'user aborted configuration',
        6: 'data overflow',
        7: 'bitstream provides data past the device\'s SRAM array',
    }


    # Length of an ECP5 part ID, in bytes.
    PART_ID_LENGTH = 4

    # Length of an ECP5 usercode, in bytes.
    USERCODE_LENGTH = 4

    # Length of an ECP5 status register, in bytes.
    STATUS_REGISTER_LENGTH = 4


    class Opcode(IntEnum):
        """ Enumeration that describes the ECP5 configuration opcodes. """

        NO_OP                                  = 0xFF

        # Read / verify the attached FPGA's part identifier.
        READ_ID                                = 0xE0
        VERIFY_ID                              = 0xE2

        # Read or program the device's usercode
        READ_USERCODE                          = 0xC0
        ISC_PROGRAM_USERCODE                   = 0xC2

        # Reads the attached FPGA's configuration status.
        LSC_READ_STATUS                        = 0x3C

        # Call REFRESH -- the equivalent of toggling the PROGRAMN pin.
        LSC_REFRESH                            = 0x79

        # Read whether the attached FPGA is still working on a command.
        LSC_CHECK_BUSY                         = 0xF0

        # Enables and disables configuration.
        ISC_ENABLE                             = 0xC6
        ISC_ENABLE_X                           = 0x74
        ISC_DISABLE                            = 0x26

        # Erase the device's SRAM.
        ISC_ERASE                              = 0x0E

        # Reset the internal CRC tracking, starting it fresh.
        LSC_RESET_CRC                          = 0x3B

        # Request that the device accept the data that follows as a contiguous bitstream.
        LSC_BITSTREAM_BURST                    = 0x7a

        # Configure the address to be programmed.
        LSC_SET_WORKING_ADDRESS                = 0x46

        # Configure the FPGA control registers.
        LSC_PROGRAM_CONTROL_REGISTER_0         = 0x22

        # Configures the FPGA with a block of data.
        LSC_PROGRAM_AND_INCREMENT_UNCOMPRESSED = 0x82
        LSC_PROGRAM_AND_INCREMENT_COMPRESSED   = 0xB8

        # Configure the FPGA's block RAM.
        LSC_SET_BLOCK_RAM_ADDRESS              = 0xF6
        LSC_SET_BLOCK_RAM_DATA                 = 0xB2

        # Configure how the device will work with an external SPI flash.
        SPI_MODE                               = 0x79

        # Mark FPGA configuration as complete.
        ISC_PROGRAM_DONE                       = 0x5E

        #
        # Opcodes known to Project Trellis, but unused.
        #
        JUMP                                   = 0b01111110
        LSC_WRITE_COMP_DIC                     = 0b00000010
        LSC_PROG_SED_CRC                       = 0b10100010
        ISC_PROGRAM_SECURITY                   = 0b11001110


    def __init__(self, cfg_pins=None, init_pin=None, program_pin=None, done_pin=None, verbose_function=None):
        """ Captures the common fields for all ECP5 programmers.

        Paramters, all optional:
            cfg_pins -- A (potentially virtual) port containing the three CFG pins that select the
                device's configuration mode. See VirtualGPIOPort for an example of a class that
                might be used for this.
            init_pin -- A GPIOPin object that connects the device's INIT_N (program status) pin.
            program_pin -- A GPIOPin object that drives the device's PROGRAM_B (program trigger) pin.
            done_pin -- A GPIOPin object that reads the status of the FPGA's done pin.

        If pins are not provided, their functionality (e.g. checking) will not be used, and it will
        be up to the subclass to handle this. Subclasses may choose to make these required.
        """

        # Store the pins for later use.
        self._cfg_pins    = cfg_pins
        self._program_pin = program_pin
        self._done_pin    = done_pin
        self._init_pin    = init_pin

        # Apply initial directions to each of our relevant pins.
        if self._cfg_pins:
            self._cfg_pins.all_output()
        if self._program_pin:
            self._program_pin.high()
        if self._done_pin:
            self._done_pin.input()
        if self._init_pin:
            self._init_pin.input()

        # Store our verbose print function.
        self._verbose_print = verbose_function if verbose_function else lambda m : None


    def _set_configuration_mode_pins(self, configuration_mode):
        """ Sets the configuration mode pins to the given binary-valued configuration mode.

        Returns True if this method was able to set the configration pins to their relevant value,
        or False otherwise.
        """

        if self._cfg_pins:
            self._cfg_pins.write(configuration_mode)
            return True
        else:
            return False



    def _restart_configuration_process(self):
        """ Attempts to strobe the PROGRAM line, to re-start the configuration process.

        Returns True iff we had the correct
        """

        if (not self._program_pin):
            return False

        # Strobe the PROGRAM_N pin, which triggers the device to accept new programming.
        self._program_pin.low()
        self._program_pin.high()

        # Wait for the device to be ready for new commands. We could poll INIT to see if
        # the initialization is complete, but TN1260 recommends we just wait 50ms.
        time.sleep(50 / 1000)



class ECP5CommandBasedProgrammer(ECP5Programmer):
    """
    Abstract base for ECP5 programmers that are command-centric (i.e. everything except Master SPI and Slave Serial.)
    To implement, override (at least) _execute_command.
    """


    def _execute_command(self, opcode, data_or_length=0, wait_for_completion=False, check_status=True, never_print=False):
        """ Issue an ECP5 configuration command.

        Parameters:
            opcode -- The opcode to issue.
            data_or_length -- A bytes-like object that contains the data to be sent; or an integer that contains
                the amount of data to be read.
            wait_for_completion -- If set, execution will block until the FPGA reports that the command is complete.
                Only necessary for long-running command.
            never_print -- True if this is a frequently-executed command (or a command called as part of this
                function's implementation). Prevents emission of verbose "what we're doing" text.
        """
        raise NotImplementedError("base classes of ECP5CommandBasedProgrammer must override _execute_command!")


    def read_id(self):
        """ Returns the identification code for the attached ECP5. """

        id_bytes = self._execute_command(self.Opcode.READ_ID, self.PART_ID_LENGTH, check_status=False)
        return int.from_bytes(id_bytes, byteorder='little')


    def part_name(self):
        """ Returns a descriptive name of the attached FPGA, if possible. """

        part_id = self.read_id()

        if part_id in self.PART_NAMES:
            return self.PART_NAMES[part_id]
        else:
            return "Unrecognized FPGA ({:08x})".format(part_id)



    def _validate_status(self, status, expect_done=False, continue_anyway=False, extra_verbose=False, expect_isc=False):
        """ Checks the status register after reading a given command. """

        def raise_error(msg):
            raise IOError(msg)

        def verbose_print(msg):
            if extra_verbose:
                self._verbose_print(msg)

        # Depending on whether we're continuing anyways, handle errors.
        if continue_anyway:
            error_handler = self._verbose_print
        else:
            error_handler = raise_error

        # Check for any error bits.
        error_code = (status >> self.STATUS_ERROR_SHIFT) & self.STATUS_ERROR_MASK
        error_text = " ({} / {:08x})".format(self.STATUS_ERROR_CODES[error_code], status)
        if status & self.STATUS_FLAG_FAIL:
            error_handler("Failed to execute last command!{}".format(error_text))
        if status & self.STATUS_FLAG_ID_ERROR:
            error_handler("Failed to verify device IDCODE!{}".format(error_text))
        if status & self.STATUS_FLAG_INVALID_COMMAND:
            error_handler("Last command was invalid!{}".format(error_text))
        #if error_code:
        #    error_handler("Error code reported. {}".format(error_text))

        # Print out some general status.
        if status:
            verbose_print("status was: {:08x}".format(status))
        if status & self.STATUS_FLAG_JTAG_ACTIVE:
            verbose_print("     - device is being controlled by JTAG.")
        if status & self.STATUS_FLAG_BUSY:
            verbose_print("     - device is busy.")
        if status & self.STATUS_FLAG_ISC_ENABLE:
            verbose_print("     - configuration enabled")
        if status & self.STATUS_FLAG_WRITEABLE:
            verbose_print("         - configuration can be written")
        if status & self.STATUS_FLAG_READABLE:
            verbose_print("         - configuration can be read back")
        if status & self.STATUS_FLAG_STANDARD_PRE:
            verbose_print("         - standard preamble detected")
        if status & self.STATUS_FLAG_SPI_FAIL:
            verbose_print("     - couldn't boot from SPI flash")
        if status & self.STATUS_FLAG_DONE:
            verbose_print("     - configuration is complete")

        # Check for DONE.
        if expect_done and not (status & self.STATUS_FLAG_DONE):
            error_handler("Configuration failed: {} / ({:08x})".format(self.STATUS_ERROR_CODES[error_code], status))


        if expect_isc and not (status & self.STATUS_FLAG_ISC_ENABLE):
            error_handler("Failed to enter ISC: {} / ({:08x})".format(self.STATUS_ERROR_CODES[error_code], status))


    def _perform_preconfiguration_tasks(self):
        """ Handles any tasks that need to be executed prior to configuration.

        Intended to allow subclasses a chance to add functionality. For example, a JTAG
        subclass would want to issue an LSC_PRELOAD here.
        """
        pass


    def _generate_bit_reversed_bitstream(self, bitstream):
        """
        Generates a copy of the provided bitstream with the bits in each byte
        reversed -- in the format the FPGA likes them for MSPI mode.
        """

        # Quick helper function to reverse the bits in our bitstream.
        def reverse_bits(num):
            binstr = "{:08b}".format(num)
            return int(binstr[::-1], 2)

        # Reverse each of the bits in each byte of the bitstream.
        #
        # This ensures that bits are shifted into the FPGA in the same
        # order as they need to be presented to the configuration logic;
        # even if the FPGA is the one commanding the flash.
        #
        bit_reversed = bytearray(bitstream)
        for i in range(len(bit_reversed)):
            bit_reversed[i] = reverse_bits(bit_reversed[i])

        return bit_reversed


    def configure(self, bitstream):
        """ Configures the attached FPGA with the relevant bitstream file.

            bitstream -- An bytes-like object containing the data to be configured into the FPGA. Any object that
                can be passed to bytearray's constructor is acceptable.
        """

        bitstream = self._generate_bit_reversed_bitstream(bitstream)

        self.chain.debugger.set_led_pattern(self.chain.debugger.LED_PATTERN_UPLOAD)

        try:
            # Ensure we're at the start of the configuration process. This also clears out any
            # existing bitstream.
            self._restart_configuration_process()

            # Perform any pre-configuration tasks necessary.
            self._perform_preconfiguration_tasks()

            # Capture the part ID, and then verify that our bitstream matches.
            # FIXME: use the bitstream file to get the ID, not our exected LUNA ID
            self._capture_part_id()
            self._execute_command(self.Opcode.VERIFY_ID, b"\x21\x11\x10\x43")

            # ???
            self._execute_command(0x1C, bits(b"\x3f" + b"\xff" * 63, 510), check_status=False, bits_per_size_unit=1)

            # Enable configuration.
            self._execute_command(self.Opcode.ISC_ENABLE, b"\x00", check_status=False)
            self.chain.run_test(2)

            status = self._read_status()
            self._validate_status(status, expect_isc=True)

            # Erase the device's SRAM.
            self._execute_command(self.Opcode.ISC_ERASE, b"\x01", wait_for_completion=True, check_status=True)
            self.chain.run_test(2)

            # Check our status.
            status = self._read_status()
            self._validate_status(status, continue_anyway=True)

            # Shift the bitstream to the FPGA; this is essentially just executing all of the
            # commands in the bitstream.
            self._execute_command(self.Opcode.LSC_SET_WORKING_ADDRESS, b"\x01")

            # Shift the bitstream to the FPGA; this is essentially just executing all of the commands in the bitstream.
            self._execute_command(self.Opcode.LSC_BITSTREAM_BURST, bitstream, check_status=False, wait_for_completion=False)

            # Idle for long enough to let the configuration take.
            self._allow_configuration_time()

            # Check the device's status.
            status = self._read_status()
            self._validate_status(status, expect_done=True)

            # Disable configuration, and allow the FPGA to start.
            self._execute_command(self.Opcode.ISC_DISABLE, check_status=False)
            self.chain.run_test(2)

            status = self._read_status()
            self._validate_status(status, expect_done=True)


        finally:
            self.chain.debugger.set_led_pattern(self.chain.debugger.LED_PATTERN_IDLE)



    def _restart_configuration_process(self):
        """ Restarts the configuration process; equivalent to toggling the PROGRAM_N pin. """

        # First, try our base-most method of using the PROGRAM pin to restart configuration.
        parent_completed = super(ECP5CommandBasedProgrammer, self)._restart_configuration_process()

        # If this worked, we're done!
        if parent_completed:
            return

        # Otherwise, we'll attempt to do the same thing using the REFRESH command.

        # Note: for now, we're going to try to use the REFRESH command;
        # but it may make sense to reset the FPGA or use the PROGRAM_N pin.
        self._execute_command(self.Opcode.LSC_REFRESH, wait_for_completion=True, check_status=False)

        # Delay 50ms to give the board time to clear its SRAM.
        time.sleep(50 / 1000)


    def trigger_reconfiguration(self):
        pass


    def _capture_part_id(self):
        """ Reads and stores the device's part ID.

        Raises an IOError if the device has a known-invalid Device ID.
        """

        self.part_id = self.read_id()

        if self.part_id in (0, 0xFFFFFFFF):
            raise IOError("Could not detect a connected FPGA (ID: {:08x}). Check your wiring?".format(self.part_id))


    def _read_status(self) :
        """ Reads the part's status from the relevant device. """

        status_bytes = self._execute_command(self.Opcode.LSC_READ_STATUS, self.STATUS_REGISTER_LENGTH,
            check_status=False, never_print=True)
        return int.from_bytes(status_bytes, byteorder='big')


    def _read_usercode(self) :
        """ Reads the part's status from the relevant device. """

        status_bytes = self._execute_command(self.Opcode.READ_USERCODE, self.USERCODE_LENGTH)
        usercode =  int.from_bytes(status_bytes, byteorder='big')

        return usercode


    def _device_is_busy(self):
        """ Checks to see if the ECP5 device is busy handling a command. """

        busy = self._execute_command(self.Opcode.LSC_CHECK_BUSY, 1, check_status=False)
        return busy[0] & 0x01


    def _wait_for_completion(self, timeout=1, context=None):
        """ Blocks until the ECP5 reports that it has completed its current processing task.

        Parameters:
            timeout -- timeout in seconds
        """

        # Compute when we should time out.
        timeout = time.monotonic() + timeout

        # Wait until the device no longer reports that it's busy.
        while self._device_is_busy():
            time.sleep(0.01)

            if time.monotonic() > timeout:
                raise IOError("ECP5 request timed out waiting for completion (context: {})".format(context))



class ECP5SlaveSPI(ECP5CommandBasedProgrammer):
    """ Class that enables configuring ECP5 FPGAs via GreatFET boards. """


    # To enter Slave SPI mode, we'll need to set CFG[2:0] to 001.
    CONFIGURATION_SELECT_VALUE = 0b001


    def __init__(self, board, spi_bus=None, *args, **kwargs):
        """ Creates a new ECP5 Slave SPI (SSPI) configuration interface.

        Parameters:
            board -- The GreatFET board to use for configuration.
            spi_bus -- The SPI bus to use for programming. If omitted, the board's
                default SPI bus will be used.

        See ECP5Programmer.__init__ for additional accepted arguments.
        """

        # Store a reference to our board and SPI bus.
        self.board = board
        self.spi = spi_bus or board.spi

        # And run the parent configuration.
        super(ECP5SlaveSPI, self).__init__(*args, **kwargs)


    def _restart_configuration_process(self):
        """ Restarts the configuration process. """

        # Configure the FPGA's configuration select, and then call the parent function.
        self._set_configuration_mode_pins(self.CONFIGURATION_SELECT_VALUE)
        super(ECP5SlaveSPI, self)._restart_configuration_process()




    def _execute_command(self, opcode, data_or_length=0, wait_for_completion=False, check_status=True, never_print=False):
        """ Issue an ECP5 configuration command.

        Parameters:
            opcode -- The opcode to issue.
            data_or_length -- A bytes-like object that contains the data to be sent; or an integer that contains
                the amount of data to be read.
            wait_for_completion -- If set, execution will block until the FPGA reports that the command is complete.
                Only necessary for long-running command.
            never_print -- True if this is a frequently-executed command (or a command called as part of this
                function's implementation). Prevents emission of verbose "what we're doing" text.
        """

        # Start our command stream with our opcode, and our three required padding bytes.
        command_stream = bytearray([opcode, 0x00, 0x00, 0x00])
        prefix_length = len(command_stream)
        length_with_receive = len(command_stream)

        # ECP5 configuration transactions are either send -or- receive, but not both.
        # Accordingly, if we have a length, this is a receive-only transaction.
        is_receive = isinstance(data_or_length, int)

        # If we have a length, rather tha a data stream, compute the total transaction length.
        if is_receive:
            length_with_receive += data_or_length

        # Otherwise, we should have a data stream. Append it to our command stream, and then
        # issue that.
        else:
            length_with_receive += len(data_or_length)
            command_stream.extend(data_or_length)

        # Print out what we're doing, if we have a verbose function.
        if not never_print:
            operand_print = "" if len(command_stream) > 16 else ": {}".format(command_stream)
            self._verbose_print("Executing {} / [{} bytes{}]".format(self.Opcode(opcode).name,
                len(command_stream), operand_print))


        # Issue the command, and capture any data send in response.
        response = self.spi.transmit(command_stream, length_with_receive)

        # If the caller has requested we wait for completion, do so.
        if wait_for_completion:
            self._wait_for_completion(context=opcode)

        if check_status:
            status = self._read_status()
            self._validate_status(status)

        # If this is a receive command, trim off our command stream and return just the response.
        if is_receive:
            return bytes(response[prefix_length:])
        else:
            return b""


class ECP5MasterSerialDirect(ECP5Programmer):
    """ ECP5 Programmer class for programming the SPI flash used for Master SPI.

    This variant expects we have a direct connection to the target flash, rather than e.g.
    programming it through JTAG.
    """

    # To enter Master SPI mode, we'll need to set CFG[2:0] to 010.
    CONFIGURATION_SELECT_VALUE = 0b010


    def __init__(self, board, chip_select=None, *args, **kwargs):
        """ Creates a new ECP5 Slave SPI (SSPI) configuration interface.

        Parameters:
            board -- The GreatFET board to use for configuration.
            chip_select -- The GPIOPin to be used for chip select, or None to use the
                board's default.
            program_pin -- The GPIO pin to be used to control the FPGA's PROGRAM_N line.

        See ECP5Programmer.__init__ for additional accepted arguments.
        """

        # If we have a Chip Select string, convert it to a GPIOPin object.
        if isinstance(chip_select, str):
            chip_select = board.gpio.get_pin(chip_select)

        # If we do have a GPIOPin for chip select, make sure it's in input mode.
        if chip_select:
            chip_select.input()

        # Call our parent constructor and let it set things up.
        super(ECP5MasterSerialDirect, self).__init__(*args, **kwargs)

        # Create our connection to the target SPI flash.
        self.flash = SPIFlash(board, chip_select_port=chip_select.get_port(),
            chip_select_pin=chip_select.get_pin(), force_page_size=256)



    def trigger_reconfiguration(self):
        """ Triggers the target FPGA to reconfigure itself from its flash chip. """

        # Configure the FPGA's configuration select, and then call the parent function.
        self._set_configuration_mode_pins(self.CONFIGURATION_SELECT_VALUE)
        super(ECP5MasterSerialDirect, self)._restart_configuration_process()



    def program(self, bitstream, progress_callback=None):
        """ Programs the target flash with the relevant bitstream; but does not trigger reconfiguration of the FPGA. """
        bitstream_bit_reversed = self._generate_bit_reversed_bitstream(bitstream)
        self.flash.write(bitstream_bit_reversed, erase_first=True, progress_callback=progress_callback)


    def configure(self, bitstream, progress_callback=None):
        """ Programs the target flash, and then triggers the FPGA to reconfigure itself from it. """
        bitstream_bit_reversed = self._generate_bit_reversed_bitstream(bitstream)
        self.program(bitstream, progress_callback)
        self.trigger_reconfiguration()




class ECP5_JTAGProgrammer(ECP5CommandBasedProgrammer):
    """ Class that enables configuring ECP5 FPGAs over JTAG. """


    def __init__(self, jtag_chain, *args, **kwargs):
        """ Parameters:
            board -- The GreatFET board to use for configuration.
            chain -- The JTAG chain used for programming.
                default SPI bus will be used.

        See ECP5Programmer.__init__ for additional accepted arguments.
        """

        # Store a reference to our board and SPI bus.
        self.chain = jtag_chain

        # And run the parent configuration.
        super(ECP5_JTAGProgrammer, self).__init__(*args, **kwargs)


    def _allow_configuration_time(self):
        self.chain.shift_instruction(0xFF, state_after='IRPAUSE')
        self.chain.run_test(100)


    def _execute_command(self, opcode, data_or_length=0, wait_for_completion=False, check_status=True, never_print=False, bits_per_size_unit=8):
        """ Issue an ECP5 configuration command.

        Parameters:
           opcode -- The opcode to issue.
            data_or_length -- A bytes-like object that contains the data to be sent; or an integer that contains
                the amount of data to be read.
            wait_for_completion -- If set, execution will block until the FPGA reports that the command is complete.
                Only necessary for long-running command.
            never_print -- True if this is a frequently-executed command (or a command called as part of this
                function's implementation). Prevents emission of verbose "what we're doing" text.
        """

        # Scan in the opcode.
        self.chain.shift_instruction(opcode, state_after='IRPAUSE', length=8)

        # ECP5 configuration transactions are either send -or- receive, but not both.
        # Accordingly, if we have a length, this is a receive-only transaction.
        is_receive = isinstance(data_or_length, int)
        if is_receive:
            length = data_or_length * bits_per_size_unit
            data   = None
        else:
            data   = data_or_length
            length = len(data) * bits_per_size_unit


        # Issue the command, and capture any data send in response.
        if data or length:
            response = self.chain.shift_data(tdi=data, length=length, state_after='DRPAUSE')
        else:
            response = b""

        # If the caller has requested we wait for completion, do so.
        if wait_for_completion:
            self._wait_for_completion(context=opcode)

        if check_status:
            status = self._read_status()
            self._validate_status(status, extra_verbose=True)

        # If this is a receive command, return the response.
        if is_receive:
            return bytes(response)
        else:
            return b""
