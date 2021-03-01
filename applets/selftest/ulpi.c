/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "platform.h"
#include "ulpi.h"

/**
 * Reads a value from a ULPI PHY register.
 */
uint8_t read_ulpi_register(enum ulpi_phy phy, uint8_t address)
{
	switch (phy) {
		case TARGET_PHY:
			while(target_ulpi_busy_read());
			target_ulpi_address_write(address);
			while(target_ulpi_busy_read());
			return target_ulpi_value_read();
		case HOST_PHY:
			while(host_ulpi_busy_read());
			host_ulpi_address_write(address);
			while(host_ulpi_busy_read());
			return host_ulpi_value_read();
		case SIDEBAND_PHY:
			while(sideband_ulpi_busy_read());
			sideband_ulpi_address_write(address);
			while(sideband_ulpi_busy_read());
			return sideband_ulpi_value_read();
	}
}



/**
 * Writes a value to a ULPI PHY register.
 */
void write_ulpi_register(enum ulpi_phy phy, uint8_t address, uint8_t value)
{
	switch (phy) {
		case TARGET_PHY:
			while(target_ulpi_busy_read());
			target_ulpi_address_write(address);
			while(target_ulpi_busy_read());
			target_ulpi_value_write(value);
			break;
		case HOST_PHY:
			while(host_ulpi_busy_read());
			host_ulpi_address_write(address);
			while(host_ulpi_busy_read());
			host_ulpi_value_write(value);
			break;
		case SIDEBAND_PHY:
			while(sideband_ulpi_busy_read());
			sideband_ulpi_address_write(address);
			while(sideband_ulpi_busy_read());
			sideband_ulpi_value_write(value);
			break;
	}
}
