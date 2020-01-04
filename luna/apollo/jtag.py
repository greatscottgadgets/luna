#
# This file is part of LUNA
#

import sys

from warnings import warn

from .support.bits import bits
from .protocol.jtag_svf import SVFParser, SVFEventHandler

# Vendor requests that implement our basic JTAG protocol.
REQUEST_JTAG_START            = 0xbf
REQUEST_JTAG_CLEAR_OUT_BUFFER = 0xb0
REQUEST_JTAG_SET_OUT_BUFFER   = 0xb1
REQUEST_JTAG_GET_IN_BUFFER    = 0xb2
REQUEST_JTAG_SCAN             = 0xb3 
REQUEST_JTAG_RUN_CLOCK        = 0xb4
REQUEST_JTAG_GO_TO_STATE      = 0xb5
REQUEST_JTAG_GET_STATE        = 0xb6
REQUEST_JTAG_STOP             = 0xbe


class JTAGPatternError(IOError):
    """ Class for errors that come from a JTAG read not matching the expected response. """

    def __init__(self, message, result):
        self.result = result
        super(JTAGPatternError, self).__init__(message)


class JTAGDevice:
    """ Class representing a single device on a JTAG scan chain. """

    DESCRIPTION = "no description available"

    # A list of supported IDCODEs for the relevant class.
    # Used unless the supports_idcode() method is overridden.
    SUPPORTED_IDCODES = []

    @classmethod
    def from_idcode(cls, idcode, position_in_chain=0):
        """ Attempts to create a JTAGDevice object that fits the provided IDCODE. """

        # Assume the generic device class is the most appropriate class for the device, initially.
        most_appropriate_class = cls

        # Search each imported subclass for the
        for subclass in cls.__subclasses__():
            if subclass.supports_idcode(idcode):
                most_appropriate_class = subclass
                break


        # Finally, create an instance of the most appropriate class for this object.
        instance = object.__new__(most_appropriate_class)
        most_appropriate_class.__init__(instance, idcode, position_in_chain)

        return instance


    @classmethod
    def supports_idcode(cls, idcode):
        """
        Returns true iff this class supports the given IDCODE.

        This default implementation uses SUPPORTED_IDCODES, but subclasses can override this
        for more nuanced behavior.
        """
        return idcode in cls.SUPPORTED_IDCODES


    def idcode(self):
        """ Returns this device's IDCODE. """
        return self._idcode


    def description(self):
        """ Returns a short description of the device. """
        return self.DESCRIPTION


    def __init__(self, idcode, position_in_chain):
        self._idcode = idcode



class JTAGChain:
    """ Class representing a JTAG scan-chain interface. """

    # Short name for this type of interface.
    INTERFACE_SHORT_NAME = "jtag"

    STATE_NUMBERS = {
        'RESET':     0,
        'IDLE':      1,

        # Data register path.
        'DRSELECT':  2,
        'DRCAPTURE': 3,
        'DRSHIFT':   4,
        'DREXIT1':   5,
        'DRPAUSE':   6,
        'DREXIT2':   7,
        'DRUPDATE':  8,

        # Instruction register path.
        'IRSELECT':  9,
        'IRCAPTURE': 10,
        'IRSHIFT':   11,
        'IREXIT1':   12,
        'IRPAUSE':   13,
        'IREXIT2':   14,
        'IRUPDATE':  15
    }



    def __init__(self, debugger, max_frequency=405e3):
        """ Creates a new JTAG scan-chain interface.

        Paramters:
            board         -- the Apollo debugger we're working with.
            max_frequency -- the maximum frequency we should attempt scan out data with
        """

        # Grab our JTAG API object.
        self.debugger = debugger

        # Configure our chain to run at the relevant frequency.
        self.frequency = int(max_frequency)
        self.max_bits_per_scan = 256 * 8


    def initialize(self):
        """ 
        Starts use of a persistent JTAG connection.
        When possible prefer using 'with' on this object.
        """
        self.__enter__()


    def __enter__(self):
        """ Starts a new JTAG communication. """

        # Enable our JTAG comms.
        self.debugger.out_request(REQUEST_JTAG_START)

        # Move to the test/reset state.
        self.move_to_state('RESET')

        return self


    def __exit__(self, item_type, value, tb):
        """ Terminates an active JTAG communication. """
        self.debugger.out_request(REQUEST_JTAG_STOP)


    def set_frequency(self, max_frequency):
        """ Sets the operating frequency of future transactions on this JTAG chain. """

        # FIXME: support this
        pass



    def initialize_chain(self):
        """ Put the scan chain into its initial state, allowing fresh JTAG communications. """

        # Pulse the TMS line five times -- this brings us into the TEST_RESET state, which resets the test logic.
        self._ensure_in_state('RESET')



    def _receive_data_chunk(self, bits_to_scan, advance_state=False):
        """ Performs a raw scan-in of data, and returns the result. """

        # Figure out how many whole bytes we'll need to read to get all of our bits.
        bytes_to_read = (bits_to_scan + 7) // 8

        # Perform the actual data scan-in...
        self.debugger.out_request(REQUEST_JTAG_SCAN, value=bits_to_scan, index=1 if advance_state else 0)

        # ... and then read the relevant data.
        result = self.debugger.in_request(REQUEST_JTAG_GET_IN_BUFFER, length=bytes_to_read)
        return bytes(result)



    def _receive_data(self, bits_to_scan):

        response = bytearray()
        self.debugger.out_request(REQUEST_JTAG_CLEAR_OUT_BUFFER)

        while bits_to_scan > 0:
            bits_in_chunk = min(bits_to_scan, self.max_bits_per_scan)
            bits_to_scan -= bits_in_chunk
            chunk = self._receive_data_chunk(bits_in_chunk)

            response.extend(chunk)

        return response


    def _pad_data_to_length(self, length_in_bits, data=None):
        """ Pads a given data set to a given length, in bits. """

        # Compute how many bytes we need the data to be.
        target_length_bytes = (length_in_bits + 7) // 8

        # If our data doesn't need padding, return it directly.
        if data and (len(data) >= target_length_bytes):
            return data

        # Create a mutable array of data; and add any data we have.
        padded = bytearray()
        if data:
            padded.extend(data)

        # Figure out how much padding we need.
        padding_necessary = target_length_bytes - len(padded)
        padded.extend("b\0" * padding_necessary)

        # Return our padded data.
        return padded


    def _transmit_data(self, bits_to_scan, data=None):
        """ Performs a raw scan-out of data, discarding any result. """
        self._scan_data(bits_to_scan, data, ignore_response=True)


    def _scan_data(self, bits_to_scan, byte_data, ignore_response=False):
        """ Performs a raw scan-in of data, and returns the result. """

        total_scanned = 0
        total_to_scan = bits_to_scan

        receive  = bytearray()
        if byte_data:
            transmit = bytearray(byte_data)

        bytes_per_chunk = self.max_bits_per_scan // 8
        bits_per_chunk  = bytes_per_chunk * 8

        while bits_to_scan:
            bits_in_chunk = min(bits_to_scan, bits_per_chunk)
            bits_to_scan -= bits_in_chunk
            advance_state = not bool(bits_to_scan)

            if byte_data:
                chunk = transmit[0:bytes_per_chunk]
                del transmit[0:bytes_per_chunk]
            else:
                chunk = None

            total_scanned += bits_in_chunk
            result = self._scan_data_chunk(bits_in_chunk, chunk, ignore_response, advance_state)

            receive.extend(result)

        return receive



    def _scan_data_chunk(self, bits_to_scan, byte_data, ignore_response=False, advance_state=False):
        """ Performs a raw scan-in of data, and returns the result. """

        # Figure out how many whole bytes we'll need to read to get all of our bits.
        bytes_to_read = (bits_to_scan + 7) // 8

        # Perform our actual data scan-in.
        # TODO: break larger-than-maximum transactions into smaller ones.
        if byte_data:
            self.debugger.out_request(REQUEST_JTAG_SET_OUT_BUFFER, data=byte_data)
        self.debugger.out_request(REQUEST_JTAG_SCAN, value=bits_to_scan, index=1 if advance_state else 0)

        if not ignore_response:
            result = self.debugger.in_request(REQUEST_JTAG_GET_IN_BUFFER, length=bytes_to_read)
        else:
            result = b""

        return result



    def _ensure_in_state(self, state):
        """
        Ensures the JTAG TAP FSM is in the given state.
        If we're not; progresses the TAP FSM by pulsing TMS until we reach the relevant state.
        """

        state_number = self.STATE_NUMBERS[state]
        self.debugger.out_request(REQUEST_JTAG_GO_TO_STATE, value=state_number)

        # TODO: remove this; this if for debugging only
        current_state_raw = self.debugger.in_request(REQUEST_JTAG_GET_STATE, length=1)
        current_state_number = int.from_bytes(current_state_raw, byteorder='little')
        assert(current_state_number == state_number)


    def move_to_state(self, state_name):
        """ Moves the JTAG scan chain to the relevant state.

        Parameters:
            state_name: The target state to wind up in, as a string. States are accepted in the format
            defined in the JTAG SVF standard, and thus should be one of:
                "RESET", "IDLE", "DRSELECT", "DRCAPTURE", "DRSHIFT", "DREXIT1", "DRPAUSE",
                "DREXIT2", "DRUPDATE", "IRSELECT", "IRCAPTURE", "IRSHIFT", "IREXIT1", "IRPAUSE",
                "IREXIT2", "IRUPDATE"
        """
        self._ensure_in_state(state_name.strip())



    def _shift_while_in_state(self, state, tdi=None, length=None, ignore_response=False, byteorder='big'):
        """ Shifts data through the chain while in the given state. """

        # Normalize our data into a bitstring type that we can easily work with.
        # This both ensures we have a known format; and implicitly handles things like padding.
        if tdi:
            data_bits = bits(tdi, length, byteorder=byteorder)

            # Bit-reverse our data, so we're sending LSB first, per the JTAG spec.
            #data_bits = bits(data_bits.to_str()[::-1])

            # Convert from our raw data to the format we'll need to send down to the device.
            bit_length = len(data_bits)
            data_bytes = data_bits.to_bytes(byteorder='big')

        else:
            if length is None:
                raise ValueError("either TDI or length must be provided!")

            bit_length = length

        # Move into our shift-DR state.
        self._ensure_in_state(state)

        # Finally, issue the transaction itself.
        if tdi and ignore_response:
            self._transmit_data(bit_length, data_bytes)
            return None
        elif tdi:
            result = self._scan_data(bit_length, data_bytes)
        else:
            result = self._receive_data(bit_length)

        # Return our data, converted back up to bits.
        return bits(result, bit_length, byteorder='big')


    def _validate_response(self, response_bits, tdo=None, mask=None):
        """ Validates the response provided by a _shift_while_in_state call, in the traditional JTAG SVF form. """

        # If we don't have any data to validate against, vacuously succeed.
        if (not tdo) or (not response_bits):
            return

        # If we have a mask, mask both the TDO value and response, and then compare.
        masked_response = mask & response_bits if mask else response_bits
        masked_tdo      = mask & tdo if mask else tdo

        if masked_response != masked_tdo:
            sys.stderr.flush()
            sys.stdout.flush()
            raise JTAGPatternError("Scan result did not match expected pattern: {} != {} (expected)!".format(
                    masked_response, masked_tdo), response_bits)


    def shift_data(self, tdi=None, length=None, tdo=None, mask=None,
            ignore_response=False, byteorder='big', state_after=None):
        """ Shifts data through the scan-chain's data register.

        Parameters:
            tdi    -- The bits to be scanned out via TDI. Can be a support.bits() object, a string of 1's and 0's,
                      an integer, or bytes. If this is an integer or bytes object, the length argument must be provided.
                      If omitted or None, a string of all zeroes will be used,
            length -- The length of the transaction to be performed, in bits. This can be longer than the TDI data;
                      in which case the transmission will be padded with zeroes.
            tdo    -- The expected data to be received from the scan operation. If this is provided, the read result
                      will be compared to this data (optionally masked by mask), and an exception will be thrown if
                      the data doesn't match this value. Designed to behave like the SVF TDO field.
            mask   -- If provided, the given tdo argument will be masked, such that only bits corresponding to a '1'
                      in this mask argument are considered when checking against 'tdo'. This is the behavior defiend
                      in the SVF standard; see it for more information.
            ignore_response -- If provided; the returned response will always be empty, and tdo and mask will be ignored.
                               This allows for slight a performance optimization, as we don't have to shuttle data back.
            byteorder       -- The byteorder to consider the tdi value in; if bytes are provided.

        Returns the bits read, or None if the response is ignored.
        """

        # Perform the core shift, and gather the response.
        response = self._shift_while_in_state('DRSHIFT', tdi=tdi, length=length, ignore_response=ignore_response,
                byteorder=byteorder)

        # Validate our response against any provided constraints.
        self._validate_response(response, tdo=tdo, mask=mask)

        if state_after:
            self.move_to_state(state_after)

        return response


    def shift_instruction(self, tdi=None, length=None, tdo=None, mask=None,
            ignore_response=False, byteorder='big', state_after=None):
        """ Shifts data through the chain's instruction register.

        Parameters:
            tdi    -- The bits to be scanned out via TDI. Can be a support.bits() object, a string of 1's and 0's,
                      an integer, or bytes. If this is an integer or bytes object, the length argument must be provided.
                      If omitted or None, a string of all zeroes will be used,
            length -- The length of the transaction to be performed, in bits. This can be longer than the TDI data;
                      in which case the transmission will be padded with zeroes.
            tdo    -- The expected data to be received from the scan operation. If this is provided, the read result
                      will be compared to this data (optionally masked by mask), and an exception will be thrown if
                      the data doesn't match this value. Designed to behave like the SVF TDO field.
            mask   -- If provided, the given tdo argument will be masked, such that only bits corresponding to a '1'
                      in this mask argument are considered when checking against 'tdo'. This is the behavior defiend
                      in the SVF standard; see it for more information.
            ignore_response -- If provided; the returned response will always be empty, and tdo and mask will be ignored.
                               This allows for slight a performance optimization, as we don't have to shuttle data back.
            byteorder       -- The byteorder to consider the tdi value in; if bytes are provided.

        Returns the bits read, or None if the response is ignored.
        """

        # Perform the core shift, and gather the response.
        response = self._shift_while_in_state('IRSHIFT', tdi=tdi, length=length, ignore_response=ignore_response,
                byteorder=byteorder)

        # Validate our response against any provided constraints.
        self._validate_response(response, tdo=tdo, mask=mask)

        if state_after:
            self.move_to_state(state_after)

        return response


    def run_test(self, cycles, from_state='IDLE', end_state=None):
        """ Places the device into the RUNTEST/IDLE (or provided) state, and pulses the JTAG clock.

        Paraameters:
            cycles -- The number of cycles for which the device should remain in the given state.
            from_state -- The state in which the cycles should be spent; defaults to IDLE.
            end_state -- The state in which the device should be placed after the test is complete.
        """

        if from_state:
            self.move_to_state(from_state)

        self.debugger.out_request(REQUEST_JTAG_RUN_CLOCK, cycles, 0)

        if end_state:
            self.move_to_state(end_state)


    def _create_device_for_idcode(self, idcode, position_in_chain):
        """ Creates a JTAGDevice object for the relevant idcode. """

        return JTAGDevice.from_idcode(idcode, position_in_chain)


    def enumerate(self, return_idcodes=False):
        """ Initializes the JTAG TAP FSM, and attempts to identify all connected devices.

        Parameters:
            return_idcodes -- If true, this method will return a list of IDCodes rather than JTAGDevice objects.

        Returns a list of JTAGDevices (return_idcodes=False) or JTAG IDCODES (return_idcodes=True).
        """

        devices = []

        # Place the JTAG TAP FSM into its initial state, so we can perform enumeration.
        self.initialize_chain()

        # Resetting the TAP FSM also automatically loaded the instruction register with the IDCODE
        # instruction, and accordingly filled the chain of data registers with each device's IDCODE.
        # We can accordingly just scan out the data using shift_data.

        # Once we (re-)initialize the chain, each device automatically loads the IDCODE instruction
        # for execution. This means that if we just scan in data, we'll receive each device's IDCODE,
        # followed by a null terminator (32 bits of zeroes).
        position_in_chain = 0
        while True:

            # Attempt to read a 32-bit IDCODE from the device.
            raw_idcode = self.shift_data(length=32)
            idcode = int.from_bytes(raw_idcode, byteorder='big')

            # If our IDCODE is all 1's, and we have no devices, we seem to be stuck at one.
            # Warn the user.
            if idcode == 0xFFFFFFFF and not devices:
                warn("TDO appears to be stuck at '1'. Check your wiring?")

            # If we've received our null IDCODE, we've finished enumerating the chain.
            # We'll also treat an all-1's IDCODE as a terminator, as this invalid IDCODE occurs
            # if TDI is stuck-at-one.
            if idcode in (0x00000000, 0xFFFFFFFF):
                break

            if return_idcodes:
                devices.append(idcode)
            else:
                devices.append(self._create_device_for_idcode(idcode, position_in_chain))

            position_in_chain += 1

        return devices


    def play_svf_instructions(self, svf_string, log_function=None, error_log_function=print):
        """ Executes a string of JTAG SVF instructions, strumming the relevant scan chain.

        svf_string   -- A string containing valid JTAG SVF instructions to be executed.
        log_function -- If provided, this function will be called with verbose operation information.
        log_error    -- This function will be used to print information about errors that occur.
        """

        # Create the parser that will run our SVF file, and run our SVF.
        parser = SVFParser(svf_string, GreatfetSVFEventHandler(self, log_function, error_log_function))
        parser.parse_file()


    def play_svf_file(self, svf_file, log_function=None, error_log_function=print):
        """ Executes the JTAG SVF instructions from the given file.

        svf_file     -- A filename or file object pointing to a JTAG SVF file.
        log_function -- If provided, this function will be called with verbose operation information.
        log_error    -- This function will be used to print information about errors that occur.
        """

        close_after = False

        if isinstance(svf_file, str):
            svf_file = open(svf_file, 'r')
            close_after = True

        self.play_svf_instructions(svf_file.read(), log_function=log_function, error_log_function=error_log_function)

        if close_after:
            svf_file.close()



class GreatfetSVFEventHandler(SVFEventHandler):
    """ SVF event handler that delegates handling of SVF instructions to a GreatFET JTAG interface. """


    def __init__(self, interface, verbose_log_function=None, error_log_function=print):
        """ Creates a new SVF event handler.

        Parameters:
            interface: The GreatFET JTAG interface that will execute our JTAG commands.
        """

        if verbose_log_function is None:
            verbose_log_function = lambda string : None
        if error_log_function is None:
            error_log_function = print

        self.interface = interface
        self.log = verbose_log_function
        self.log_error = error_log_function

        # Assume that after a data / instruction shift operation that we'll
        # wind up in the IDLE state, per the SVF standard. The SVF file can
        # override these defaults
        self.end_dr_state = 'IDLE'
        self.end_ir_state = 'IDLE'

        # By default, don't have any headers or trailers for IR or DR shifts.
        # The SVF can override these using the HDR/TDR/HIR/TIR instructions.
        nullary_padding = {'tdi': bits(), 'tdo': bits(), 'mask': bits(), }
        self.dr_header  = nullary_padding.copy()
        self.dr_trailer = nullary_padding.copy()
        self.ir_header  = nullary_padding.copy()
        self.ir_trailer = nullary_padding.copy()

        # Store default masks for our ShiftIR and ShiftDR instructions.
        self.last_dr_mask  = None
        self.last_dr_smask = None
        self.ir_mask  = None
        self.ir_smask = None


        self.interface.move_to_state('RESET')


    def svf_frequency(self, frequency):
        """Called when the ``FREQUENCY`` command is encountered."""
        self.log (" -- FREQUENCY set to {}".format(frequency))
        self.interface.set_frequency(frequency)


    def svf_trst(self, mode):
        """Called when the ``TRST`` command is encountered."""
        warn('SVF provided TRST command; but this implementation does not yet support driving the TRST line')


    def svf_state(self, state, path):
        """Called when the ``STATE`` command is encountered."""

        # Visit each state in any intermediate paths provided...
        if path:
            for intermediate in path:
                self.log("STATE; Moving through {}.".format(intermediate))
                self.interface.move_to_state(intermediate)

        # ... ensuring we end up in the relevant state.
        self.log("Moving to {} STATE.".format(state))
        self.interface.move_to_state(state)


    def svf_endir(self, state):
        """Called when the ``ENDIR`` command is encountered."""
        self.log("Moving to {} after each Shift-IR.".format(state))
        self.end_dr_state = state


    def svf_enddr(self, state):
        """Called when the ``ENDDR`` command is encountered."""
        self.log("Moving to {} after each Shift-DR.".format(state))
        self.end_ir_state = state


    def svf_hir(self, **header):
        """Called when the ``HIR`` command is encountered."""
        self.log("Applying Shift-IR prefix. ")
        self.ir_header = header


    def svf_tir(self, **trailer):
        self.log("Applying Shift-IR suffix. ")
        self.ir_trailer = trailer


    def svf_hdr(self, **header):
        """Called when the ``HDR`` command is encountered."""
        self.log("Applying Shift-DR header. ")
        self.dr_header = header


    def svf_tdr(self, **trailer):
        """Called when the ``TDR`` command is encountered."""
        self.log("Applying Shift-DR suffix. ")
        self.dr_trailer = trailer


    def svf_sir(self, **data):
        """Called when the ``SIR`` command is encountered."""

        # Append our header and trailer to each of our arguments.
        arguments = {}
        for arg, value in data.items():
            header  = self.ir_header[arg] if (arg in self.ir_header) else bits()
            trailer = self.ir_trailer[arg] if (arg in self.ir_trailer) else bits()
            arguments[arg] = (header + value + trailer) if value else None

        if data['mask']:
            self.ir_mask = data['mask']
        if data['smask']:
            self.ir_smask = data['mask']

        self.log("Performing SHIFT-IR:")
        self.log(   "out:      {}".format(arguments['tdi']))
        self.log(   "expected: {}".format(arguments['tdo']))
        self.log(   "mask:     {}".format(arguments['mask']))
        try:
            result = self.interface.shift_instruction(tdi=arguments['tdi'], tdo=arguments['tdo'], mask=arguments['mask'])
        except JTAGPatternError as e:
            self.log(   "in:       {} [FAIL]\n".format(e.result))
            self.log_error("\n\n<!> Failure while performing SHIFT-IR: \n    " + str(e))
            raise

        self.log(   "in:       {} [OK]\n".format(result))


    def svf_sdr(self, **data):
        """Called when the ``SDR`` command is encountered."""

        # Append our header and trailer to each of our arguments.
        arguments = {}
        for arg, value in data.items():
            header  = self.dr_header[arg] if (arg in self.dr_header and self.dr_header[arg]) else bits()
            trailer = self.dr_trailer[arg] if (arg in self.dr_trailer and self.dr_header[arg]) else bits()
            arguments[arg] = (header + value + trailer) if value else None

        if data['mask']:
            self.dr_mask = data['mask']
        if data['smask']:
            self.dr_smask = data['mask']

        self.log("Performing SHIFT-DR:")
        self.log(   "out:      {}".format(arguments['tdi']))
        self.log(   "expected: {}".format(arguments['tdo']))
        self.log(   "mask:     {}".format(arguments['mask']))
        try:
            result = self.interface.shift_data(tdi=arguments['tdi'], tdo=arguments['tdo'], mask=arguments['mask'])
        except JTAGPatternError as e:
            self.log(   "in:       {} [FAIL]\n".format(e.result))
            self.log_error("\n\n<!> Failure while performing SHIFT-DR: \n    " + str(e))
            raise
        self.log(   "in:       {} [OK]\n".format(result))


    def svf_runtest(self, run_state, run_count, run_clock, min_time, max_time, end_state):
        """Called when the ``RUNTEST`` command is encountered."""
        self.log("Running test for {} cycles.".format(run_count))
        self.interface.run_test(run_count, from_state=run_state, end_state=end_state)


    def svf_piomap(self, mapping):
        """Called when the ``PIOMAP`` command is encountered."""
        raise NotImplementedError("This implementation does not yet support PIOMAP.")

    def svf_pio(self, vector):
        """Called when the ``PIO`` command is encountered."""
        raise NotImplementedError("This implementation does not yet support PIO.")
