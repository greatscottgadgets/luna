/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#pragma once

#include "resources.h"

// Type representing each of our PHYs.
enum ulpi_phy {
	TARGET_PHY,
	HOST_PHY,
	SIDEBAND_PHY
};


/**
 * Reads a value from a ULPI PHY register.
 */
int16_t read_ulpi_register(enum ulpi_phy phy, uint8_t address);

/**
 * Writes a value to a ULPI PHY register.
 */
int write_ulpi_register(enum ulpi_phy phy, uint8_t address, uint8_t value);
