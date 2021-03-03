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
int16_t read_ulpi_register(enum ulpi_phy phy, uint8_t address)
{
	switch (phy) {
		case TARGET_PHY:
			if (while_with_timeout(target_ulpi_busy_read, 100)) {
				return -1;
			}
			target_ulpi_address_write(address);

			if (while_with_timeout(target_ulpi_busy_read, 100)) {
				return -1;
			}
			return target_ulpi_value_read();

		case HOST_PHY:
			if (while_with_timeout(host_ulpi_busy_read, 100)) {
				return -1;
			}
			host_ulpi_address_write(address);

			if (while_with_timeout(host_ulpi_busy_read, 100)) {
				return -1;
			}
			return host_ulpi_value_read();
		case SIDEBAND_PHY:
			if (while_with_timeout(sideband_ulpi_busy_read, 100)) {
				return -1;
			}
			sideband_ulpi_address_write(address);

			if (while_with_timeout(sideband_ulpi_busy_read, 100)) {
				return -1;
			}
			return sideband_ulpi_value_read();
	}
}



/**
 * Writes a value to a ULPI PHY register.
 */
int write_ulpi_register(enum ulpi_phy phy, uint8_t address, uint8_t value)
{
	switch (phy) {
		case TARGET_PHY:
			if (while_with_timeout(target_ulpi_busy_read, 100)) {
				return -1;
			}
			target_ulpi_address_write(address);

			if (while_with_timeout(target_ulpi_busy_read, 100)) {
				return -1;
			}
			target_ulpi_value_write(value);
			break;

		case HOST_PHY:
			if (while_with_timeout(host_ulpi_busy_read, 100)) {
				return -1;
			}
			host_ulpi_address_write(address);

			if (while_with_timeout(host_ulpi_busy_read, 100)) {
				return -1;
			}
			host_ulpi_value_write(value);
			break;
		case SIDEBAND_PHY:
			if (while_with_timeout(sideband_ulpi_busy_read, 100)) {
				return -1;
			}
			sideband_ulpi_address_write(address);

			if (while_with_timeout(sideband_ulpi_busy_read, 100)) {
				return -1;
			}
			sideband_ulpi_value_write(value);
			break;
	}

	return 0;
}
