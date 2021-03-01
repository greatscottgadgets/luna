/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "platform.h"
#include "psram.h"

// FIXME: remove
#include "uart.h"

/**
 * Reads a value from a ULPI PHY register.
 */
uint32_t read_psram_register(uint32_t address)
{
	uart_puts("waiting to write\n");
	while(psram_busy_read());

	uart_puts("writing addr\n");
	psram_address_write(address);

	uart_puts("waiting to read\n");
	while(psram_busy_read());

	uart_puts("doing a read\n");
	return psram_value_read();
}