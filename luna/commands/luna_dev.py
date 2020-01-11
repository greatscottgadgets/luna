#!/usr/bin/env python3
#
# This file is part of LUNA
#

from __future__ import print_function

import os
import sys
import ast
import time
import errno
import shutil
import tempfile
import argparse

from luna.apollo import ApolloDebugger
from luna.apollo.jtag import JTAGChain, JTAGPatternError
from luna.apollo.ecp5 import ECP5_JTAGProgrammer
from luna.apollo.onboard_jtag import *

# Grab references to the gateware applets we'll need to perform some of the debug functions.
from luna.gateware.platform import get_appropriate_platform
from luna.gateware.applets.dc_flash import DebugControllerFlashBridge


COMMAND_HELP_TEXT = \
"""configure  -- Uploads a bitstream to the device's FPGA over JTAG.
erase      -- Clears the attached board's configuration flash.
program    -- Programs the target bitstream onto the attached FPGA.
jtag-scan  -- Prints information about devices on the onboard JTAG chain.
flash-scan -- Attempts to detect any attached configuration flashes.
svf        -- Plays a given SVF file over JTAG.
spi        -- Sends the given list of bytes over debug-SPI, and returns the response.
spi-reg    -- Reads or writes to a provided register over the debug-SPI.
"""


def print_chain_info(device, log_function, log_error, args):
    """ Command that prints information about devices connected to the scan chain to the console. """

    with device.jtag as jtag:
        log_function("Scanning for connected devices...")
        detected_devices = jtag.enumerate()

        # If devices exist on the scan chain, print their information.
        if detected_devices:
            log_function("{} device{} detected on the scan chain:\n".format(
                        len(detected_devices), 's' if len(detected_devices) > 1 else ''))

            for device in detected_devices:
                log_function("    {:08x} -- {}".format(device.idcode(), device.description()))


            log_function('')

        else:
            log_function("No devices found.\n")


def play_svf_file(device, log_function, log_error, args):
    """ Command that prints the relevant flash chip's information to the console. """

    if not args.argument:
        log_error("You must provide an SVF filename to play!\n")
        sys.exit(-1)

    with device.jtag as jtag:
        try:
            jtag.play_svf_file(args.argument, log_function=log_function, error_log_function=log_error)
        except JTAGPatternError:
            # Our SVF player has already logged the error to stderr.
            log_error("")


def configure_ecp5(device, log_function, log_error, args):
    """ Command that prints information about devices connected to the scan chain to the console. """

    with device.jtag as jtag:

        programmer = ECP5_JTAGProgrammer(jtag)

        with open(args.argument, "rb") as f:
            bitstream = f.read()

        programmer.configure(bitstream)


def reconfigure_ecp5(device, log_function, log_error, args):
    """ Command that requests the attached ECP5 reconfigure itself from its MSPI flash. """

    with device.jtag as jtag:
        programmer = ECP5_JTAGProgrammer(jtag)
        programmer.trigger_reconfiguration()


def debug_spi(device, log_function, log_error, args):

    # Try to figure out what data the user wants to send.
    data_raw = ast.literal_eval(args.argument)
    if isinstance(data_raw, int):
        data_raw = [data_raw]

    data_to_send = bytes(data_raw)
    response     = device.spi.transfer(data_to_send)

    print("response: {}".format(response))


def debug_spi_register(device, log_function, log_error, args):

    # Try to figure out what data the user wants to send.
    address = int(args.argument, 0)
    if args.value:
        value = int(args.value, 0)
        is_write = True
    else:
        value = 0
        is_write = False

    response = device.spi.register_transaction(address, is_write=is_write, value=value)
    print("0x{:08x}".format(response))


def set_up_for_flashing(device, log_function):
    """ Sets up the device for flashing; e.g. by uploading a configuration image. """

    # Check to see if we have a gateware loaded that responds with the right magic numbers.
    # If so, we're already set up for flashing.
    try:
        if device.spi.register_read(1) == 0x53504946:
            return
    except:
        pass

    # Create a temporary buld directory, so we're not cluttering the user's working directory
    # with nMigen build output.
    build_dir = tempfile.mkdtemp(suffix="build")

    try:
        # Build and upload a set of gateware that will give us access to the target flash.
        log_function("No compatible gateware detected. Generating and uploading a flash-bridge gateware...")
        target_platform = get_appropriate_platform()
        target_platform.build(DebugControllerFlashBridge(), do_program=True, build_dir=build_dir)

        # Validate that we seem to have an SPI flash.
        with device.flash as flash:
            info, _ = flash.read_flash_info()
            assert(info is not None)
        log_function("Flash bridge ready; target SPI should be accessible.\n")
    finally:
        shutil.rmtree(build_dir)



def print_flash_info(device, log_function, log_error, args):
    """ Command that prints information about the connected SPI flash. """
    set_up_for_flashing(device, log_function)

    with device.flash as flash:
        flash_id, description = flash.read_flash_info()

    if flash_id is None:
        log_error("No connected flash detected.\n")
        sys.exit(-1)
    else:
        log_function("Detected a configuration flash!")
        log_function("    {:04x} -- {}".format(flash_id, description))
        log_function()


def erase_config_flash(device, log_function, log_error, args):
    """ Command that erases the connected configuration flash. """
    set_up_for_flashing(device, log_function)

    with device.flash as flash:
        flash.erase()


def program_config_flash(device, log_function, log_error, args):
    """ Command that programs a given bitstream into the device's configuration flash. """
    set_up_for_flashing(device, log_function)

    with open(args.argument, "rb") as f:
        bitstream = f.read()

    with device.flash as flash:
        flash.program(bitstream, log_function)


def read_out_config_flash(device, log_function, log_error, args):
    """ Command that programs a given bitstream into the device's configuration flash. """
    set_up_for_flashing(device, log_function)
   
    # For now, always read back a ECP5-12F.
    read_back_length = 582376

    read_back_length = 512

    with device.flash as flash:
        bitstream = flash.readback(read_back_length, log_function=log_function)

    with open(args.argument, "wb") as f:
        f.write(bitstream)



def main():

    commands = {
        # Info queries
        'jtag-scan':   print_chain_info,
        'flash-scan':  print_flash_info,

        # JTAG commands
        'svf':         play_svf_file,
        'configure':   configure_ecp5,
        'reconfigure': reconfigure_ecp5,

        # SPI debug exchanges
        'spi':         debug_spi,
        'spi-reg':     debug_spi_register,
    
        # SPI flash commands
        'erase':       erase_config_flash,
        'program':     program_config_flash,
        'readback':    read_out_config_flash
    }


    # Set up a simple argument parser.
    parser = argparse.ArgumentParser(description="Utility for LUNA development via an onboard Debug Controller.",
            formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('command', metavar='command:', choices=commands, help=COMMAND_HELP_TEXT)
    parser.add_argument('argument', metavar="[argument]", nargs='?',
                        help='the argument to the given command; often a filename')
    parser.add_argument('value', metavar="[value]", nargs='?',
                        help='the value to a register write command')

    args = parser.parse_args()
    device = ApolloDebugger()

    # Grab our log functions.
    # FIXME: select these
    log_function, log_error = print, print

    # Execute the relevant command.
    command = commands[args.command]
    command(device, log_function, log_error, args)


if __name__ == '__main__':
    main()
