/*
 * Code for interacting with the FPGA via JTAG.
 *
 * This JTAG driver is intended to be as simple as possible in order to facilitate
 * configuration and debugging of the attached FPGA. It is not intended to be a general-
 * purpose JTAG link.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <tusb.h>
#include <apollo_board.h>

#include <jtag.h>


extern uint8_t jtag_in_buffer[256];
extern uint8_t jtag_out_buffer[256];


/**
 * Request that performs the actual JTAG scan event.
 * Arguments:
 *     wValue: the number of bits to scan; total
 *     wIndex: 1 if the given command should advance the FSM
 */
bool handle_jtag_request_scan(uint8_t rhport, tusb_control_request_t const* request)
{
	// We can't handle 0-bit transfers; fail out.
	if (!request->wValue) {
		return false;
	}

	jtag_tap_shift(jtag_out_buffer, jtag_in_buffer, request->wValue, request->wIndex);
	return tud_control_xfer(rhport, request, NULL, 0);
}

