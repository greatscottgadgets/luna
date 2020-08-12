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
 * By default, assume the implementation has no quirks.
 * Boards can override this function to specify their quirks, which are defined in jtag.h
 */
uint32_t get_quirks(void)
{
	return JTAG_QUIRK_FLIP_BITS_IN_WHOLE_BYTES;
}


/**
 * Hook that performs hardware-specific initialization.
 */
void jtag_platform_init(void)
{
	//
	// Set up the LPC SSP to handle JTAG communications.
	//
	Chip_SSP_Init(LPC_SSP1);

	// We'll operate an as SPI controller...
	Chip_SSP_SetFormat(LPC_SSP1, SSP_BITS_8, SSP_FRAMEFORMAT_SPI, SSP_CLOCK_CPHA1_CPOL1);
	Chip_SSP_SetMaster(LPC_SSP1, 1);

	// ... and target 10-15 MHz as our SPI rate.
	Chip_Clock_SetSSP1ClockDiv(1);
	Chip_SSP_SetBitRate(LPC_SSP1, 10000000UL);
	Chip_SSP_Enable(LPC_SSP1);
}


/**
 * Switches to using the SSP SPI engine for JTAG.
 * This mode is faster, but can only send whole frames.
 */
static void switch_jtag_to_spi(void)
{
	Chip_IOCON_PinMux(LPC_IOCON, _DAISHO_PORT(TCK_GPIO), _DAISHO_PIN(TCK_GPIO), IOCON_DIGMODE_EN, IOCON_FUNC2);
	Chip_IOCON_PinMux(LPC_IOCON, _DAISHO_PORT(TDO_GPIO), _DAISHO_PIN(TDO_GPIO), IOCON_DIGMODE_EN, IOCON_FUNC2);
	Chip_IOCON_PinMux(LPC_IOCON, _DAISHO_PORT(TDI_GPIO), _DAISHO_PIN(TDI_GPIO), IOCON_DIGMODE_EN, IOCON_FUNC2);
}


/**
 * Switches to using GPIO for JTAG.
 * This mode is much, much slower, but can handle individual bytes.
 */
static void switch_jtag_to_bitbang(void)
{
	Chip_IOCON_PinMux(LPC_IOCON, _DAISHO_PORT(TCK_GPIO), _DAISHO_PIN(TCK_GPIO), IOCON_DIGMODE_EN, IOCON_FUNC0);
	Chip_IOCON_PinMux(LPC_IOCON, _DAISHO_PORT(TDO_GPIO), _DAISHO_PIN(TDO_GPIO), IOCON_DIGMODE_EN, IOCON_FUNC0);
	Chip_IOCON_PinMux(LPC_IOCON, _DAISHO_PORT(TDI_GPIO), _DAISHO_PIN(TDI_GPIO), IOCON_DIGMODE_EN, IOCON_FUNC0);
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

	// Create a configuration with which to drive the fast section of our transfer.
	Chip_SSP_DATA_SETUP_T transfer_configuration = {
		.tx_data = &jtag_out_buffer,
		.rx_data = &jtag_in_buffer,
		.tx_cnt  = 0,
		.rx_cnt  = 0,
		.length  = bytes_to_send_bulk
	};

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
	switch_jtag_to_spi();
	Chip_SSP_RWFrames_Blocking(LPC_SSP1, &transfer_configuration);

	// Switch back to GPIO mode, and send the remainder using the slow method.
	switch_jtag_to_bitbang();
	if (bits_to_send_slow) {
		jtag_tap_shift(jtag_out_buffer + bytes_to_send_bulk, jtag_in_buffer + bytes_to_send_bulk,
				bits_to_send_slow, request->wIndex);
	}
	return tud_control_xfer(rhport, request, NULL, 0);
}
