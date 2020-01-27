/*
 * Code for interacting with the FPGA via JTAG.
 * This file is part of LUNA.
 *
 * This JTAG driver is intended to be as simple as possible in order to facilitate
 * configuration and debugging of the attached FPGA. It is not intended to be a general-
 * purpose JTAG link.
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include <tusb.h>
#include <sam.h>
#include <hal/include/hal_gpio.h>

#include "led.h"
#include "spi.h"
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
 * Request that performs the actual JTAG scan event.
 * Arguments:
 *     wValue: the number of bits to scan; total
 *     wIndex: 1 if the given command should advance the FSM
 */
bool handle_jtag_request_scan(uint8_t rhport, tusb_control_request_t const* request)
{
	// Our bulk method can only send whole bytes; so send as many bytes as we can
	// using the fast method; and then send the remainder using our slow method.
	size_t bytes_to_send_bulk = request->wValue / 8;
	size_t bits_to_send_slow  = request->wValue % 8;

	// We can't handle 0-byte transfers; fail out.
	if (!bits_to_send_slow && !bytes_to_send_bulk) {
		return false;
	}

	// If this would scan more than we have buffer for, fail out.
	if (bytes_to_send_bulk > sizeof(jtag_out_buffer)) {
		return false;
	}

	// If we're going to advance state, always make sure the last bit is sent using the slow method,
	// so we can handle JTAG TAP state advancement on the last bit. If we don't have any bits to send slow,
	// send the last byte slow.
	if (!bits_to_send_slow && request->wIndex) {
		bytes_to_send_bulk--;
		bits_to_send_slow = 8;
	}

	// Switch to SPI mode, and send the bulk of the transfer using it.
	spi_configure_pinmux(SPI_FPGA_JTAG);
	spi_send(SPI_FPGA_JTAG, jtag_out_buffer, jtag_in_buffer, bytes_to_send_bulk);

	// Switch back to GPIO mode, and send the remainder using the slow method.
	spi_release_pinmux(SPI_FPGA_JTAG);
	if (bits_to_send_slow) {
		jtag_tap_shift(jtag_out_buffer + bytes_to_send_bulk, jtag_in_buffer + bytes_to_send_bulk,
				bits_to_send_slow, request->wIndex);
	}
	return tud_control_xfer(rhport, request, NULL, 0);
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

	spi_init(SPI_FPGA_JTAG, true, false, 1, 1, 1);

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
