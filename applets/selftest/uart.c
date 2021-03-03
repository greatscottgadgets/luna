/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "uart.h"

/**
 * Transmits a single charater over our example UART.
 */
void print_char(char c)
{
	while(!uart_tx_rdy_read());
	uart_tx_data_write(c);
}


/**
 * Receives a single character from the UART. Blocking.
 */
char uart_getchar(void)
{
	while(!uart_rx_rdy_read());
	return uart_rx_data_read();
}


/**
 * Transmits a string over our UART.
 */
void uart_puts(char *str)
{
	for (char *c = str; *c; ++c) {
		if (*c == '\n') {
			print_char('\r');
		}

		print_char(*c);
	}
}


static void uart_put_hexit(uint8_t hexit)
{
	if (hexit < 10) {
		print_char(hexit + '0');
	}
	else {
		print_char((hexit - 10) + 'A');
	}
}

/**
 * Prints the hex value of a byte to the UART console.
 */
void uart_print_byte(uint8_t value)
{
	uart_puts("0x");
	uart_put_hexit(value >> 4);
	uart_put_hexit(value & 0x0f);
}


/**
 * Prints the hex value of a byte to the UART console.
 */
void uart_print_word(uint16_t value)
{
	uart_puts("0x");
	uart_put_hexit((value >> 12) & 0x0f);
	uart_put_hexit((value >>  8) & 0x0f);
	uart_put_hexit((value >>  4) & 0x0f);
	uart_put_hexit((value >>  0) & 0x0f);
}