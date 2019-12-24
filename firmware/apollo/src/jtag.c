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
#include <hal/include/hal_delay.h>


// JTAG comms buffers.
uint8_t jtag_in_buffer[256];
uint8_t jtag_out_buffer[256];


/**
 * GPIO pin numbers for each of the JTAG pins.
 */
enum {
	TDO_GPIO = PIN_PA10,
	TDI_GPIO = PIN_PA08,
	TCK_GPIO = PIN_PA09,
	TMS_GPIO = PIN_PA11
};


void wait_for_next_edge_time(void)
{
}


/**
 * Generates a single cycle of bit-banged JTAG.
 */
static inline bool jtag_tick(bool tdi)
{
	bool tdo;

	tdo = gpio_get_pin_level(TDO_GPIO);
	gpio_set_pin_level(TCK_GPIO, true);

	// Apply our TDI and TMS values.
	gpio_set_pin_level(TDI_GPIO, tdi);

	// Create a falling edge.
	gpio_set_pin_level(TCK_GPIO, false);

	// Return the scanned in value from TDI.
	return tdo;
}


/**
 * Performs any start-of-day tasks necessary to talk JTAG to our FPGA.
 */
void jtag_init(void)
{
	gpio_set_pin_function(TDO_GPIO, 0);
	gpio_set_pin_function(TDI_GPIO, 0);
	gpio_set_pin_function(TCK_GPIO, 0);
	gpio_set_pin_function(TMS_GPIO, 0);


	// Set up each of our JTAG pins.
	gpio_set_pin_direction(TDO_GPIO, GPIO_DIRECTION_IN);
	gpio_set_pin_direction(TDI_GPIO, GPIO_DIRECTION_OUT);
	gpio_set_pin_direction(TCK_GPIO, GPIO_DIRECTION_OUT);
	gpio_set_pin_direction(TMS_GPIO, GPIO_DIRECTION_OUT);


	gpio_set_pin_direction(PIN_PA16, GPIO_DIRECTION_IN);
	gpio_set_pin_pull_mode(PIN_PA16, GPIO_PULL_UP);
}


/**
 * Core JTAG scan routine -- performs the actual JTAG I/O.
 */
int jtag_scan(uint8_t bit_count)
{
	// FIXME: during scan, we should switch to the SPI sercom
	// and blast bits out that way; rather than doing this slow
	// bitbang. This is mostly a stepping stone for initial debug.

	uint8_t transmit_byte = 0, receive_byte = 0;
	uint8_t bits_left_in_tx_byte = 0, bits_left_in_rx_byte = 8;

	unsigned tx_position = 0, rx_position = 0;

	// Ensure TMS isn't set, so we don't advance through the FSM.
	gpio_set_pin_level(TMS_GPIO, false);

	// While there are any bits remaining to transfer, do so.
	while (bit_count) {
		bool to_transmit, received;

		// If we don't have any bits queued to process for the current byte,
		// get a new byte, and commit the data we've already worked with.
		if (!bits_left_in_tx_byte) {
			transmit_byte = jtag_out_buffer[tx_position++];
			bits_left_in_tx_byte = 8;
		}
		if (!bits_left_in_rx_byte) {
			jtag_in_buffer[rx_position++] = receive_byte;
			bits_left_in_rx_byte = 8;
		}

		// Grab the LSB, and queue it for transmit.
		to_transmit = transmit_byte & 1;
		transmit_byte >>= 1;

		// Perform out transmission.
		received = jtag_tick(to_transmit);

		// Merge the received bit into our active rx byte.
		receive_byte = (receive_byte >> 1) | (received ? 0x80 : 0);

		--bit_count;
		--bits_left_in_tx_byte;
		--bits_left_in_rx_byte;
	}

	// If we have bits left in the byte we're building,
	// shift our data into the LSB spot and then add it to our response.
	receive_byte >>= bits_left_in_rx_byte;
	jtag_in_buffer[rx_position++] = receive_byte;

	return 0;
}


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
 */
bool handle_jtag_request_scan(uint8_t rhport, tusb_control_request_t const* request)
{
	// If this would scan more than we have buffer for, fail out.
	if (request->wValue > sizeof(jtag_out_buffer)) {
		return false;
	}

	// Perform the scan, and ACK.
	jtag_scan(request->wValue);
	return tud_control_xfer(rhport, request, NULL, 0);
}


/**
 * Runs the JTAG clock for a specified amount of ticks.
 * Arguments:
 *     wValue: The number of clock cycles to run.
 *     wIndex: If non-zero, TMS will be held high during the relevant cycles..
 */
bool handle_jtag_run_clock(uint8_t rhport, tusb_control_request_t const* request)
{
	gpio_set_pin_level(TMS_GPIO, request->wIndex);

	for (unsigned i = 0; i < request->wValue; ++i) {
		jtag_tick(false);
	}

	gpio_set_pin_level(TMS_GPIO, false);

	return tud_control_xfer(rhport, request, NULL, 0);
}
