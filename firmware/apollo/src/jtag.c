/*
 * Code for interacting with the FPGA via JTAG.
 *
 * This JTAG driver is intended to be as simple as possible in order to facilitate
 * configuration and debugging of the attached FPGA. It is not intended to be a general-
 * purpose JTAG link.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2019-2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include <tusb.h>
#include <apollo_board.h>

#include "led.h"
#include "jtag.h"
#include "uart.h"


// JTAG comms buffers.
uint8_t jtag_in_buffer[256] __attribute__((aligned(4)));
uint8_t jtag_out_buffer[256] __attribute__((aligned(4)));


/**
 * Simple request that clears the JTAG out buffer.
 */
bool handle_jtag_request_clear_out_buffer(uint8_t rhport, tusb_control_request_t const* request)
{
	memset(jtag_out_buffer, 0, sizeof(jtag_out_buffer));
	return tud_control_xfer(rhport, request, NULL, 0);
}


/**
 * Simple request that sets the JTAG out buffer's contents.
 * This is used to set the data to be transmitted during the next scan.
 */
bool handle_jtag_request_set_out_buffer(uint8_t rhport, tusb_control_request_t const* request)
{
	// If we've been handed too much data, stall.
	if (request->wLength > sizeof(jtag_out_buffer)) {
		return false;
	}

	// Copy the relevant data into our OUT buffer.
	return tud_control_xfer(rhport, request, jtag_out_buffer, request->wLength);
}


/**
 * Simple request that gets the JTAG in buffer's contents.
 * This is used to fetch the data received during the last scan.
 */
bool handle_jtag_request_get_in_buffer(uint8_t rhport, tusb_control_request_t const* request)
{
	uint16_t length = request->wLength;

	// If the user has requested more data than we have, return only what we have.
	if (length > sizeof(jtag_in_buffer)) {
		length = sizeof(jtag_in_buffer);
	}

	// Send up the contents of our IN buffer.
	return tud_control_xfer(rhport, request, jtag_in_buffer, length);
}



/**
 * Runs the JTAG clock for a specified amount of ticks.
 * Arguments:
 *     wValue: The number of clock cycles to run.
 */
bool handle_jtag_run_clock(uint8_t rhport, tusb_control_request_t const* request)
{
	jtag_wait_time(request->wValue);
	return tud_control_xfer(rhport, request, NULL, 0);
}


/**
 * Runs the JTAG clock for a specified amount of ticks.
 * Arguments:
 *     wValue: The state number to go to. See jtag.h for state numbers.
 */
bool handle_jtag_go_to_state(uint8_t rhport, tusb_control_request_t const* request)
{
	jtag_go_to_state(request->wValue);
	return tud_control_xfer(rhport, request, NULL, 0);
}


/**
 * Reads the current JTAG TAP state. Mostly intended as a debug aid.
 */
bool handle_jtag_get_state(uint8_t rhport, tusb_control_request_t const* request)
{
	static uint8_t jtag_state;

	jtag_state = jtag_current_state();
	return tud_control_xfer(rhport, request, &jtag_state, sizeof(jtag_state));
}


/**
 * Initializes JTAG communication.
 */
bool handle_jtag_start(uint8_t rhport, tusb_control_request_t const* request)
{
	led_set_blink_pattern(BLINK_JTAG_CONNECTED);
	jtag_init();


	return tud_control_xfer(rhport, request, NULL, 0);
}


/**
 * De-initializes JTAG communcation; and stops driving the scan chain.
 */
bool handle_jtag_stop(uint8_t rhport, tusb_control_request_t const* request)
{
	led_set_blink_pattern(BLINK_IDLE);
	jtag_deinit();

	return tud_control_xfer(rhport, request, NULL, 0);
}
