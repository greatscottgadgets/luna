/**
 * This file is part of LUNA.
 */

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


int main(void)
{
	uart_puts("Hello, world!\r\n");
	while(1);
}
