/**
 * Interface code for communicating with the FPGA over the Debug SPI connection.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <tusb.h>
#include <apollo_board.h>

#include <led.h>
#include <debug_spi.h>

extern uint8_t spi_in_buffer[256 + 4];
extern uint8_t spi_out_buffer[256 + 4];


// Imported internal functions from main debug_spi.c:
void debug_spi_send(uint8_t *tx_buffer, uint8_t *rx_buffer, size_t length);


/**
 * Request that sends a block of data over our debug SPI.
 */
bool handle_flash_spi_send(uint8_t rhport, tusb_control_request_t const* request)
{
	// If we've been handed too much data, stall.
	if (request->wLength > sizeof(spi_out_buffer)) {
		return false;
	}

	// Queue a transfer that will receive the relevant SPI data.
	// We'll perform the send itself once the data transfer is complete.
	return tud_control_xfer(rhport, request, spi_out_buffer, request->wLength);
}


bool handle_flash_spi_send_complete(uint8_t rhport, tusb_control_request_t const* request)
{
	// Ensure that we're actively sending...
	gpio_set_pin_level(PIN_FLASH_CS, false);

	// ... send the data...
	debug_spi_send(spi_out_buffer, spi_in_buffer, request->wLength);

	// ... and end the tranmission, unless we've been instructed to keep the line open.
	if (!request->wValue) {
		gpio_set_pin_level(PIN_FLASH_CS, true);
	}

	return true;
}
