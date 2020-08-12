/*
 * Code for interacting with the FPGA via JTAG.
 *
 * This JTAG driver is intended to be as simple as possible in order to facilitate
 * configuration and debugging of the attached FPGA. It is not intended to be a general-
 * purpose JTAG link.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2019 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef __JTAG_H__
#define __JTAG_H__

/**
 * JTAG implementation quirk flags.
 */
enum
{
	// Some serial engines can only send bytes from MSB to LSB, rather than
	// the LSB to MSB that JTAG requires. Since we're typically using a serial
	// engine to send whole bytes, this requires whole bytes to be flipped, but
	// not any straggling bits. Setting this quirk will automatically handle this case.
	JTAG_QUIRK_FLIP_BITS_IN_WHOLE_BYTES = (1 << 0)
};

typedef enum e_TAPState
{
	STATE_TEST_LOGIC_RESET =  0,
	STATE_RUN_TEST_IDLE    =  1,
	STATE_SELECT_DR_SCAN   =  2,
	STATE_CAPTURE_DR       =  3,
	STATE_SHIFT_DR         =  4,
	STATE_EXIT1_DR         =  5,
	STATE_PAUSE_DR         =  6,
	STATE_EXIT2_DR         =  7,
	STATE_UPDATE_DR        =  8,
	STATE_SELECT_IR_SCAN   =  9, 
	STATE_CAPTURE_IR       = 10,
	STATE_SHIFT_IR         = 11,
	STATE_EXIT1_IR         = 12,
	STATE_PAUSE_IR         = 13,
	STATE_EXIT2_IR         = 14,
	STATE_UPDATE_IR        = 15
} jtag_tap_state_t;


/**
 * Performs the start-of-day tasks necessary to talk JTAG to our FPGA.
 */
void jtag_init(void);


/**
 * De-inits the JTAG connection, so the JTAG chain. is no longer driven.
 */
void jtag_deinit(void);


/**
 * Moves to a given JTAG state.
 */
void jtag_goto_state(int state);


/**
 * Performs a raw TAP scan.
 */
void jtag_tap_shift(
	uint8_t *input_data,
	uint8_t *output_data,
	uint32_t data_bits,
	bool must_end);


void jtag_wait_time(uint32_t microseconds);

void jtag_go_to_state(unsigned state);

uint8_t jtag_current_state(void);

/**
 * Simple handler that clears the JTAG out buffer.
 */
bool handle_jtag_request_clear_out_buffer(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Simple request that sets the JTAG out buffer's contents.
 * This is used to set the data to be transmitted during the next scan.
 */
bool handle_jtag_request_set_out_buffer(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Simple request that gets the JTAG in buffer's contents.
 * This is used to fetch the data received during the last scan.
 */
bool handle_jtag_request_get_in_buffer(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Request that performs the actual JTAG scan event.
 * Arguments:
 *     wValue: the number of bits to scan; total
 */
bool handle_jtag_request_scan(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Runs the JTAG clock for a specified amount of ticks.
 * Arguments:
 *     wValue: The number of clock cycles to run.
 *     wIndex: If non-zero, TMS will be held high during the relevant cycles..
 */
bool handle_jtag_run_clock(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Initializes JTAG communication.
 */
bool handle_jtag_start(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Runs the JTAG clock for a specified amount of ticks.
 * Arguments:
 *     wValue: The state number to go to. See jtag.h for state numbers.
 */
bool handle_jtag_go_to_state(uint8_t rhport, tusb_control_request_t const* request);


/**
 * De-initializes JTAG communcation; and stops driving the scan chain.
 */
bool handle_jtag_stop(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Reads the current JTAG TAP state. Mostly intended as a debug aid.
 */
bool handle_jtag_get_state(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Reads information about this device's JTAG implementation.
 * 
 * Responds with two uint32s:
 *    - the maximum JTAG buffer size, in bytes
 *    - a bitfield indicating any quirks present
 */
bool handle_jtag_get_info(uint8_t rhport, tusb_control_request_t const* request);

#endif
