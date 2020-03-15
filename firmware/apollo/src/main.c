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
#include <apollo_board.h>

#include "led.h"
#include "jtag.h"
#include "fpga.h"
#include "console.h"
#include "debug_spi.h"
//#include "selftest.h"



/**
 * Main round-robin 'scheduler' for the execution tasks.
 */
int main(void)
{
	board_init();
	tusb_init();

	fpga_io_init();
	led_init();
	debug_spi_init();

	// Trigger an FPGA reconfiguration; so the FPGA automatically
	// configures itself from its SPI ROM on reset. This effectively
	// makes the RESET button reset both the uC and the FPGA.
	trigger_fpga_reconfiguration();

	while (1) {
		tud_task(); // tinyusb device task
		console_task();
		heartbeat_task();
	}

	return 0;
}
