#
# This file is part of LUNA.
#

import sys
import shutil
import logging
import tempfile
import argparse

from nmigen import Elaboratable
from .gateware.platform import get_appropriate_platform

# Log formatting strings.
LOG_FORMAT_COLOR = "\u001b[37;1m%(levelname)-8s| \u001b[0m\u001b[1m%(module)-12s|\u001b[0m %(message)s"
LOG_FORMAT_PLAIN = "%(levelname)-8s:n%(module)-12s>%(message)s"


def top_level_cli(fragment, *pos_args, **kwargs):
    """ Runs a default CLI that assists in building and running gateware.

        If the user's options resulted in the board being programmed, this returns the fragment
        that was programmed onto the board. Otherwise, it returns None.
    """

    name = fragment.__name__ if callable(fragment) else fragment.__class__.__name__

    parser = argparse.ArgumentParser(description=f"Gateware generation/upload script for '{name}' gateware.")
    parser.add_argument('--output', '-o', metavar='filename', help="Build and output a bitstream to the given file.")
    parser.add_argument('--erase', '-E', action='store_true',
         help="Clears the relevant FPGA's flash before performing other options.")
    parser.add_argument('--upload', '-U', action='store_true',
         help="Uploads the relevant design to the target hardware. Default if no options are provided.")
    parser.add_argument('--flash', '-F', action='store_true',
         help="Flashes the relevant design to the target hardware's configuration flash.")
    parser.add_argument('--dry-run', '-D', action='store_true',
         help="When provided as the only option; builds the relevant bitstream without uploading or flashing it.")
    parser.add_argument('--keep-files', action='store_true',
         help="Keeps the local files in the default `build` folder.")

    args = parser.parse_args()
    platform = get_appropriate_platform()

    # Set up our logging / output.
    if sys.stdout.isatty():
        log_format = LOG_FORMAT_COLOR
    else:
        log_format = LOG_FORMAT_PLAIN

    logging.basicConfig(level=logging.INFO, format=log_format)

    # If this isn't a fragment directly, interpret it as an object that will build one.
    if callable(fragment):
        fragment = fragment(*pos_args, **kwargs)

    # If we have no other options set, build and upload the relevant file.
    if (args.output is None and not args.flash and not args.erase and not args.dry_run):
        args.upload = True

    # Once the device is flashed, it will self-reconfigure, so we
    # don't need an explicitly upload step; and it implicitly erases
    # the flash, so we don't need an erase step.
    if args.flash:
        args.erase = False
        args.upload = False

    # Build the relevant gateware, uploading if requested.
    build_dir = "build" if args.keep_files else tempfile.mkdtemp()

    # Build the relevant files.
    try:
        if args.erase:
            logging.info("Erasing flash...")
            platform.toolchain_erase()
            logging.info("Erase complete.")

        join_text = "and uploading gateware to attached" if args.upload else "for"
        logging.info(f"Building {join_text} {platform.name}...")

        products = platform.build(fragment,
            do_program=args.upload,
            build_dir=build_dir
        )

        logging.info(f"{'Upload' if args.upload else 'Build'} complete.")

        # If we're flashing the FPGA's flash, do so.
        if args.flash:
            logging.info("Programming flash...")
            platform.toolchain_flash(products)
            logging.info("Programming complete.")

        # If we're outputting a file, write it.
        if args.output:
            bitstream =  products.get("top.bit")
            with open(args.output, "wb") as f:
                f.write(bitstream)

        # Return the fragment we're working with, for convenience.
        if args.upload or args.flash:
            return fragment

    # Clean up any directories we've created.
    finally:
        if not args.keep_files:
            shutil.rmtree(build_dir)

    return None


