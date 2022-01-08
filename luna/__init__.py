#
# This file is part of LUNA.
#

import os
import sys
import shutil
import logging
import tempfile
import argparse

from amaranth           import Elaboratable
from amaranth._unused   import MustUse

# Log formatting strings.
LOG_FORMAT_COLOR = "\u001b[37;1m%(levelname)-8s| \u001b[0m\u001b[1m%(module)-12s|\u001b[0m %(message)s"
LOG_FORMAT_PLAIN = "%(levelname)-8s:n%(module)-12s>%(message)s"


def configure_default_logging(level=logging.INFO, logger=logging):

    # Set up our logging / output.
    if sys.stdout.isatty():
        log_format = LOG_FORMAT_COLOR
    else:
        log_format = LOG_FORMAT_PLAIN

    logger.basicConfig(level=logging.INFO, format=log_format)


def top_level_cli(fragment, *pos_args, cli_soc=None, **kwargs):
    from .gateware.platform import get_appropriate_platform

    """ Runs a default CLI that assists in building and running gateware.

        If the user's options resulted in the board being programmed, this returns the fragment
        that was programmed onto the board. Otherwise, it returns None.

        Parameters:
            fragment  -- The fragment instance to be built; or a callable that returns a fragment,
                         such as a Elaborable type. If the latter is provided, any keyword or positional
                         arguments not specified here will be passed to this callable.
            cli_soc   -- Optional. If a SoC design provides a SimpleSoc, options will be provided for generating
                         build artifacts, such as header or linker files; instead of elaborating a design.
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
    parser.add_argument('--fpga', metavar='part_number',
         help="Overrides build configuration to build for a given FPGA. Useful if no FPGA is connected during build.")
    parser.add_argument('--console', metavar="port",
         help="Attempts to open a convenience 115200 8N1 UART console on the specified port immediately after uploading.")

    # If we have SoC options, print them to the command line.
    if cli_soc:
        parser.add_argument('--generate-c-header', action='store_true',
            help="If provided, a C header file for this design's SoC will be printed to the stdout. Other options ignored.")
        parser.add_argument('--generate-ld-script', action='store_true',
            help="If provided, a linker script for design's SoC memory regions be printed to the stdout. Other options ignored.")
        parser.add_argument('--get-fw-address', action='store_true',
            help="If provided, the utility will print the address firmware should be loaded to to stdout. Other options ignored.")


    # Disable UnusedElaboarable warnings until we decide to build things.
    # This is sort of cursed, but it keeps us categorically from getting UnusedElaborable warnings
    # if we're not actually buliding.
    MustUse._MustUse__silence = True

    args = parser.parse_args()
    configure_default_logging()

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


    # If we've been asked to generate a C header, generate -only- that.
    if cli_soc and args.generate_c_header:
        cli_soc.generate_c_header(platform_name=get_appropriate_platform().name)
        sys.exit(0)

    # If we've been asked to generate linker region info, generate -only- that.
    if cli_soc and args.generate_ld_script:
        cli_soc.generate_ld_script()
        sys.exit(0)

    if cli_soc and args.get_fw_address:
        print(f"0x{cli_soc.main_ram_address():08x}")
        sys.exit(0)

    # Build the relevant gateware, uploading if requested.
    build_dir = "build" if args.keep_files else tempfile.mkdtemp()

    # Build the relevant files.
    try:
        platform = get_appropriate_platform()

        # If we have a toolchain override, apply it to our platform.
        toolchain = os.getenv("LUNA_TOOLCHAIN")
        if toolchain:
            platform.toolchain = toolchain

        if args.fpga:
            platform.device = args.fpga

        if args.erase:
            logging.info("Erasing flash...")
            platform.toolchain_erase()
            logging.info("Erase complete.")

        join_text = "and uploading gateware to attached" if args.upload else "for"
        logging.info(f"Building {join_text} {platform.name}...")

        # If we have an SoC, allow it to perform any pre-elaboration steps it wants.
        # This allows it to e.g. build a BIOS or equivalent firmware.
        if cli_soc and hasattr(cli_soc, 'build'):
            cli_soc.build(build_dir=build_dir)


        # Now that we're actually building, re-enable Unused warnings.
        MustUse._MustUse__silence = False
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

        # If we're expecting a console, open one.
        if args.console:
            import serial.tools.miniterm

            # Clear our arguments, so they're not parsed by miniterm.
            del sys.argv[1:]

            # Run miniterm with our default port and baudrate.
            serial.tools.miniterm.main(default_port=args.console, default_baudrate=115200)

        # Return the fragment we're working with, for convenience.
        if args.upload or args.flash:
            return fragment

    # Clean up any directories we've created.
    finally:
        if not args.keep_files:
            shutil.rmtree(build_dir)

    return None


