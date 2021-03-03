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
	// Wait for things to become ready.
	if(while_with_timeout(psram_busy_read, 100)) {
		return -1;
	}

	// Apply the address we're targeting.
	psram_address_write(address);

	// Wait for things to be come ready.
	if(while_with_timeout(psram_busy_read, 100)) {
		return -1;
	}

	// Finally, read the value back.
	return psram_value_read();
}