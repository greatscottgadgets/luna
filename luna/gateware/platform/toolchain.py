#
# This file is part of LUNA.
#
# Copyright (c) 2020-2024 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Utilities for managing LUNA gateware toolchains. """

import importlib
import logging
import os
import shutil

def configure_toolchain(platform):
    """ Checks if all the required tools for the Yosys toolchain are available.

        If there are missing tools it will attempt to fall back to YoWASP instead.

        Returns:
            True if a valid toolchain has been configured. Otherwise False.
    """

    if platform.has_required_tools():
        # All good, no further hanky-panky required.
        return True

    # Do we have yowasp available to us?
    logging.info(f"Failed to locate {platform.toolchain} toolchain, trying YoWASP.")
    logging.debug("Checking for required tools:")
    for tool in platform.required_tools:
        logging.debug(f"    {tool}")

    problems = 0

    # Check whether yowasp-yosys is installed:
    try:
        import yowasp_yosys
        logging.debug(f"Found module: {yowasp_yosys.__name__}")
    except Exception as e:
        problems += 1
        logging.warning(e)

    # Check whether yowasp-nextpnr-<target> is installed:
    try:
        nextpnr = next(filter(lambda x: x.startswith("nextpnr-"), platform.required_tools))
        yowasp_nextpnr = importlib.import_module("yowasp_" + nextpnr.replace('-', '_'))
        logging.debug(f"Found module: {yowasp_nextpnr.__name__}")
    except Exception as e:
        problems += 1
        logging.warning(e)

    # Check whether the YoWASP binaries are on the system PATH:
    for tool in platform.required_tools:
        env_var     = tool.replace('-', '_').upper()
        yowasp_tool = "yowasp-" + tool
        path = shutil.which(yowasp_tool)
        if not path:
            problems += 1
            logging.warning(f"'{yowasp_tool}' is not on the system PATH.")
        else:
            logging.debug(f'Setting {env_var}="{yowasp_tool}"')
            os.environ[env_var] = yowasp_tool

    if problems == 0:
        logging.info("YoWASP configured successfully.")
    else:
        logging.info(f"{problems} problems encountered while configuring YoWASP.")
        logging.info(f"You can install it with:")
        logging.info(f"    pip install yowasp-yosys yowasp-{nextpnr}")
        return False

    return True
