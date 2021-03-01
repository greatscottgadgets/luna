/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "platform.h"

void sleep_ms(uint16_t milliseconds)
{
	// Set our timer to count down from the relevant value...
	timer_ctr_write(60 * 1000 * milliseconds);

	// And block until that time has passed.
	while(timer_ctr_read());
}


void platform_bringup(void)
{
	// Enable our timer for use as a simple, software count-down.
	// We'll disable its event, and disable it from reloading, so it stays 0 when it's supposed to be.
	timer_interrupt_disable();
	timer_reload_write(0);
	timer_en_write(1);

	// Give the platform a few ms to start up before we enable the UART.
	// This is useful on newer LUNA platforms, which multiplex their JTAG and UART.
	sleep_ms(10);

	uart_interrupt_disable();
	uart_enabled_write(1);
	uart_divisor_write(520);
}


void dispatch_isr(void)
{
}
