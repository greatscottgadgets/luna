/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

// Include our automatically generated resource file.
// This allows us to work with e.g. our registers no matter what address they're assigned.
#include "resources.h"


/**
 * Transmits a single charater over our example UART.
 */
void print_char(char c)
{
	while(!uart_tx_rdy_read());
	uart_tx_data_write(c);
}


/**
 * Transmits a string over our UART.
 */
void uart_puts(char *str)
{
	for (char *c = str; *c; ++c) {
		print_char(*c);
	}
}


void dispatch_isr(void)
{
	if(timer_interrupt_pending()) {
		timer_ev_pending_write(timer_ev_pending_read());
		leds_output_write(~leds_output_read());
	}
}


int main(void)
{
	uint8_t led_value = 0b101010;
	leds_output_write(led_value);

	// Set up our timer to generate LED blinkies.
	timer_reload_write(0xA00000);
	timer_en_write(1);
	timer_ev_enable_write(1);

	// Enable our timer's interrupt.
	irq_setie(1);
	timer_interrupt_enable();

	// Say hello, on our UART.
	uart_puts("Hello, world!\r\n");
	while(1);
}
