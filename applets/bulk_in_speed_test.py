#!/usr/bin/env python3
# pylint: disable=no-member
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os
import sys
import logging
import time

import usb1

from luna.gateware.applets.speed_test import USBInSpeedTestDevice, USBInSuperSpeedTestDevice, BULK_ENDPOINT_NUMBER

from luna import top_level_cli, configure_default_logging

# Set the total amount of data to be used in our speed test.
TEST_DATA_SIZE = 1 * 1024 * 1024
TEST_TRANSFER_SIZE = 16 * 1024

# Size of the host-size "transfer queue" -- this is effectively the number of async transfers we'll
# have scheduled at a given time.
TRANSFER_QUEUE_DEPTH = 16


def run_speed_test():
    """ Runs a simple speed test, and reports throughput. """

    total_data_exchanged = 0
    failed_out = False

    _messages = {
        1: "error'd out",
        2: "timed out",
        3: "was prematurely cancelled",
        4: "was stalled",
        5: "lost the device it was connected to",
        6: "sent more data than expected."
    }

    def _should_terminate():
        """ Returns true iff our test should terminate. """
        return (total_data_exchanged > TEST_DATA_SIZE) or failed_out


    def _transfer_completed(transfer: usb1.USBTransfer):
        """ Callback executed when an async transfer completes. """
        nonlocal total_data_exchanged, failed_out

        status = transfer.getStatus()

        # If the transfer completed.
        if status in (usb1.TRANSFER_COMPLETED,):

            # Count the data exchanged in this packet...
            total_data_exchanged += transfer.getActualLength()

            # ... and if we should terminate, abort.
            if _should_terminate():
                return

            # Otherwise, re-submit the transfer.
            transfer.submit()

        else:
            failed_out = status



    with usb1.USBContext() as context:

        # Grab a reference to our device...
        device = context.openByVendorIDAndProductID(0x16d0, 0x0f3b)

        # ... and claim its bulk interface.
        device.claimInterface(0)

        # Submit a set of transfers to perform async comms with.
        active_transfers = []
        for _ in range(TRANSFER_QUEUE_DEPTH):

            # Allocate the transfer...
            transfer = device.getTransfer()
            transfer.setBulk(0x80 | BULK_ENDPOINT_NUMBER, TEST_TRANSFER_SIZE, callback=_transfer_completed, timeout=1000)

            # ... and store it.
            active_transfers.append(transfer)


        # Start our benchmark timer.
        start_time = time.time()

        # Submit our transfers all at once.
        for transfer in active_transfers:
            transfer.submit()

        # Run our transfers until we get enough data.
        while not _should_terminate():
            context.handleEvents()

        # Figure out how long this took us.
        end_time = time.time()
        elapsed = end_time - start_time

        # Cancel all of our active transfers.
        for transfer in active_transfers:
            if transfer.isSubmitted():
                transfer.cancel()

        # If we failed out; indicate it.
        if (failed_out):
            logging.error(f"Test failed because a transfer {_messages[failed_out]}.")
            sys.exit(failed_out)


        bytes_per_second = total_data_exchanged / elapsed
        logging.info(f"Exchanged {total_data_exchanged / 1000000}MB total at {bytes_per_second / 1000000}MB/s.")


if __name__ == "__main__":

    # If our environment is suggesting we rerun tests, do so.
    if os.getenv('LUNA_RERUN_TEST'):
        configure_default_logging()
        logging.info("Running speed test without rebuilding...")
        run_speed_test()

    # Otherwise, build and run our tests.
    else:
        # Selectively create our device to be either USB3 or USB2 based on the
        # SuperSpeed variable.
        if os.getenv('LUNA_SUPERSPEED'):
            device = top_level_cli(USBInSuperSpeedTestDevice)
        else:
            device = top_level_cli(USBInSpeedTestDevice,
                                   fs_only=bool(os.getenv('LUNA_FULL_ONLY')))

        logging.info("Giving the device time to connect...")
        time.sleep(5)

        if device is not None:
            logging.info(f"Starting bulk in speed test.")
            run_speed_test()
