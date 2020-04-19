/**
 * This file is part of LUNA.
 */


#define UART_TX_ADDR 0x80000000

/**
 * Transmits a single charater over our example UART.
 */
void print_char(char c)
{
	volatile char *const tx = (void *)UART_TX_ADDR;
	*tx = c;
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
