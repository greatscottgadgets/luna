/**
 * Code for basic FPGA interfacing.
 * This file is part of LUNA.
 */

#include <bsp/board.h>
#include <hal/include/hal_gpio.h>

// List of pins used for FPGA interfacing.
enum {
	PIN_PROG = PIN_PA17
};


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
