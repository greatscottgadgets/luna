/**
 * Code for basic FPGA interfacing.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <bsp/board.h>
#include <apollo_board.h>


enum {
	PIN_FRONTEND_EN  = _DAISHO_GPIO(0, 20),

	PIN_VREG_EN_1V1  = _DAISHO_GPIO(0, 17),
	PIN_VREG_EN_1V2  = _DAISHO_GPIO(0, 18),
	PIN_VREG_EN_1V8  = _DAISHO_GPIO(1, 28),
	PIN_VREG_EN_2V5  = _DAISHO_GPIO(0, 16),
	PIN_VREG_EN_3V3  = _DAISHO_GPIO(0, 16),
	PIN_VREG_EN_3V3A = _DAISHO_GPIO(0, 14),
};


static void fpga_initialize_power(void)
{
	gpio_t rail_enables[] = {
		PIN_FRONTEND_EN, PIN_VREG_EN_1V1, PIN_VREG_EN_1V2, PIN_VREG_EN_1V8,
		PIN_VREG_EN_2V5, PIN_VREG_EN_3V3, PIN_VREG_EN_3V3A
	};

	// Start up with all of the regulators off.
	for (unsigned i = 0; i < TU_ARRAY_SIZE(rail_enables); ++i) {
		gpio_set_pin_direction(rail_enables[i], GPIO_DIRECTION_OUT);
		gpio_set_pin_level(rail_enables[i], false);
	}
}


static void fpga_core_power_sequence(void)
{
	gpio_t rail_enables[] = {
		PIN_VREG_EN_1V2, PIN_VREG_EN_2V5, PIN_VREG_EN_1V8, PIN_VREG_EN_1V1
	};

	// Sequence each of our regulators on.
	for (unsigned i = 0; i < TU_ARRAY_SIZE(rail_enables); ++i) {
		gpio_set_pin_level(rail_enables[i], true);
	}
}




/**
 * Sets up the I/O pins needed to configure the FPGA.
 */
void fpga_io_init(void)
{
	fpga_initialize_power();
	board_delay(1000);
	fpga_core_power_sequence();
	board_delay(1000);
}


/**
 * Requests that the FPGA clear its configuration and try to reconfigure.
 */
void trigger_fpga_reconfiguration(void)
{
	// FIXME: TODO
}
