/**
 * This file is part of LUNA.
 */


// Include our automatically generated resource file.
// This allows us to work with e.g. our registers no matter 
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
	uint8_t led_value = 0b101010;
	leds_output_write(led_value);

	// Set up our timer to generate LED blinkies.
	timer_en_write(1);
	timer_reload_write(0x100000);

	// Say hello, on our UART.
	uart_puts("Hello, world!\r\n");

	// And blink our LEDs.
	while(1) {
		if (timer_ctr_read() == 1) {
			led_value = ~led_value;
			leds_output_write(led_value);
		}
	}
}
