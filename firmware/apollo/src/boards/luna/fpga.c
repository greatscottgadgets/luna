/**
 * Code for basic FPGA interfacing.
 * This file is part of LUNA.
 */

#include <bsp/board.h>
#include <hal/include/hal_gpio.h>

// List of pins used for FPGA interfacing.
enum {
	DONE_GPIO    = PIN_PA15,
	PROGRAM_GPIO = PIN_PA16,
	INIT_GPIO    = PIN_PA17,

	PIN_PROG =     PIN_PA17
};


/**
 * Sets up the I/O pins needed to configure the FPGA.
 */
void fpga_io_init(void)
{
	// Don't actively drive the FPGA configration pins...
	gpio_set_pin_direction(DONE_GPIO,    GPIO_DIRECTION_IN);
	gpio_set_pin_direction(INIT_GPIO,    GPIO_DIRECTION_IN);

	// ... but keep PROGRAM_N out of applying a program...
	gpio_set_pin_level(PROGRAM_GPIO, true);
	gpio_set_pin_direction(PROGRAM_GPIO, GPIO_DIRECTION_IN);

	// ... and apply their recommended pull configuration.
	gpio_set_pin_pull_mode(PROGRAM_GPIO, GPIO_PULL_UP);
	gpio_set_pin_pull_mode(DONE_GPIO,    GPIO_PULL_UP);
}


/**
 * Requests that the FPGA clear its configuration and try to reconfigure.
 */
void trigger_fpga_reconfiguration(void)
{
	gpio_set_pin_direction(PIN_PROG, GPIO_DIRECTION_OUT);
	gpio_set_pin_level(PIN_PROG, false);

	board_delay(1);

	gpio_set_pin_level(PIN_PROG, true);
	gpio_set_pin_direction(PIN_PROG, GPIO_DIRECTION_IN);
}
