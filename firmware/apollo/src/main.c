/* 
 * The MIT License (MIT)
 *
 * Copyright (c) 2019 Katherine J. Temkin <kate@ktemkin.com>
 * Copyright (c) 2019 Great Scott Gadgets <ktemkin@greatscottgadgets.com>
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 */

#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#include <tusb.h>
#include <bsp/board.h>
#include <hal/include/hal_gpio.h>

#include "led.h"
#include "spi.h"
#include "jtag.h"
#include "selftest.h"

enum {
	DONE_GPIO    = PIN_PA15,
	PROGRAM_GPIO = PIN_PA16,
	INIT_GPIO    = PIN_PA17,
};


void io_init(void)
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
 * Main round-robin 'scheduler' for the execution tasks.
 */
int main(void)
{
	board_init();
	tusb_init();

	io_init();
	led_init();
	selftest_init();

	// Set up our SPI debug and JTAG connections.
	spi_init(SPI_FPGA_DEBUG, false, true);

	while (1) {
		tud_task(); // tinyusb device task
		heartbeat_task();
	}

	return 0;
}
