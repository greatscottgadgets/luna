#!/usr/bin/env python3
#
# This file is part of LUNA
#

from __future__ import print_function

import os
import sys
import errno
import argparse

from tqdm import tqdm

from luna.apollo import ApolloDebugger
from luna.apollo.jtag import JTAGChain, JTAGPatternError
from luna.apollo.ecp5 import ECP5_JTAGProgrammer
from luna.apollo.onboard_jtag import *


COMMAND_HELP_TEXT = \
"""configure -- Uploads a bitstream to the device's FPGA over JTAG.
jtag-scan -- Prints information about devices on the onboard JTAG chain.
svf       -- Plays a given SVF file over JTAG.
fpga-id   -- Reads an ECP5 FPGA ID out over JTAG.
"""


def print_chain_info(jtag, log_function, log_error, args):
    """ Command that prints information about devices connected to the scan chain to the console. """

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


def play_svf_file(jtag, log_function, log_error, args):
    """ Command that prints the relevant flash chip's information to the console. """

    if not args.filename:
        log_error("You must provide an SVF filename to play!\n")
        sys.exit(-1)

    try:
        jtag.play_svf_file(args.filename, log_function=log_function, error_log_function=log_error)
    except JTAGPatternError:
        # Our SVF player has already logged the error to stderr.
        log_error("")


def configure_ecp5(jtag, log_function, log_error, args):
    """ Command that prints information about devices connected to the scan chain to the console. """

    programmer = ECP5_JTAGProgrammer(jtag)

    with open(args.filename, "rb") as f:
        bitstream = f.read()

    programmer.configure(bitstream)



def print_fpga_idcode(jtag, log_function, log_error, args):

    jtag.move_to_state('IDLE')

    jtag.shift_instruction(0xe0, state_after='IRPAUSE')
    print(jtag.shift_data(length=32, state_after='DRPAUSE'))



def main():

    commands = {
        'jtag-scan': print_chain_info,
        'svf': play_svf_file,
        'fpga-id': print_fpga_idcode,
        'configure': configure_ecp5
    }


    # Set up a simple argument parser.
    parser = argparse.ArgumentParser(description="Utility for LUNA development via an onboard Debug Controller.",
            formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('command', metavar='command:', choices=commands, help=COMMAND_HELP_TEXT)
    parser.add_argument('filename', metavar="[filename]", nargs='?',
                        help='the filename to read from, for SVF playback')

    args = parser.parse_args()
    device = ApolloDebugger()

    if args.command == 'scan':
        args.verbose = True
    elif args.filename == "-":
        args.verbose = False

    # Grab our log functions.
    # FIXME: select these
    log_function, log_error = print, print

    with JTAGChain(device) as jtag:

        # Execute the relevant command.
        command = commands[args.command]
        command(jtag, log_function, log_error, args)


if __name__ == '__main__':
    main()
