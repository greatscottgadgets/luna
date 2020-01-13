#
# This file is part of LUNA.
#

import shutil
import tempfile
import argparse

from nmigen import Elaboratable
from .gateware.platform import get_appropriate_platform

def top_level_cli(fragment, *pos_args, **kwargs):
    """ Runs a default CLI that assists in building and running gateware. """

    parser = argparse.ArgumentParser(description="Gateware generation/upload script for '{}' gateware.".format(fragment.__name__))
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

    # If this isn't a fragment directly, interpret it as an object that will build one.
    if callable(fragment):
        fragment = fragment(*pos_args, **kwargs)

    # If we have no other options set, build and upload the relevant file.
    if (args.output is None and not args.flash and not args.erase and not args.dry_run):
        args.upload = True

    # Once the device is flashed, it will self-reconfigure, so we
    # don't need an explicitly upload step; and it implicltly erases
    # the flash, so we don't need an erase step.
    if args.flash:
        args.erase = False
        args.upload = False

    # Build the relevant gateware, uploading if requested.
    build_dir = "build" if args.keep_files else tempfile.mkdtemp()

    # Build the relevant files.
    try:
        if args.erase:
            platform.toolchain_erase()

        products = platform.build(fragment,
            do_program=args.upload, 
            build_dir=build_dir
        )

        # If we're flashing the FPGA's flash, do so.
        if args.flash:
            platform.toolchain_flash(products)
        
        # If we're outputting a file, write it.
        if args.output:
            bitstream =  products.get("top.bit")
            with open(args.output, "wb") as f:
                f.write(bitstream)

    # Clean up any directories we've created.
    finally:
        if not args.keep_files:
            shutil.rmtree(build_dir)


    
