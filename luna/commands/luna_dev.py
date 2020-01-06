#!/usr/bin/env python3
#
# This file is part of LUNA
#

from __future__ import print_function

import os
import sys
import ast
import errno
import argparse

from luna.apollo import ApolloDebugger
from luna.apollo.jtag import JTAGChain, JTAGPatternError
from luna.apollo.ecp5 import ECP5_JTAGProgrammer
from luna.apollo.onboard_jtag import *


COMMAND_HELP_TEXT = \
"""configure -- Uploads a bitstream to the device's FPGA over JTAG.
jtag-scan -- Prints information about devices on the onboard JTAG chain.
svf       -- Plays a given SVF file over JTAG.
spi       -- Sends the given list of bytes over debug-SPI, and returns the response.
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


def debug_spi(device, log_function, log_error, args):

    # Try to figure out what data the user wants to send.
    data_raw = ast.literal_eval(args.argument)
    if isinstance(data_raw, int):
        data_raw = [data_raw]

    data_to_send = bytes(data_raw)
    response     = device.spi.transfer(data_to_send)

    print("response: {}".format(response))




def main():

    commands = {
        'jtag-scan': print_chain_info,
        'svf':       play_svf_file,
        'configure': configure_ecp5,
        'spi':       debug_spi
    }


    # Set up a simple argument parser.
    parser = argparse.ArgumentParser(description="Utility for LUNA development via an onboard Debug Controller.",
            formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('command', metavar='command:', choices=commands, help=COMMAND_HELP_TEXT)
    parser.add_argument('argument', metavar="[argument]", nargs='?',
                        help='the argument to the given command; often a filename')

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
