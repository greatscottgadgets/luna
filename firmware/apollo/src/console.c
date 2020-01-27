/**
 * Console handling code.
 * This file is part of LUNA.
 */

#include <tusb.h>

#include "led.h"
#include "uart.h"


extern bool uart_active;


/**
 * Pass any data received via UART directly up to the host.
 */
void uart_byte_received_cb(uint8_t byte)
{
	tud_cdc_write_char(byte);
	tud_cdc_write_flush();
}


/**
 * Main task that handles console I/O.
 */
void console_task(void)
{
	if (!tud_cdc_connected()) {
		return;
	}

	// We can send data to the FPGA over UART iff:
	//  - there's data waiting for us to send, and
	//  - the UART has room in its FIFO
	//
	// If both conditions are met, send data.
	while (uart_ready_for_write() && tud_cdc_available()) {
		uint8_t byte = tud_cdc_read_char();
		uart_nonblocking_write(byte);
	}

}

//
// We defer initializing our UART until we get a CDC connection.
//
// This prevents contention if the FPGA lines are used for something else,
// but makes everything seem to Just Work (TM) once the user starts using
// the CDC-ACM connection.
//


/**
 * Call-back issued when the host's line-coding changes.
 */
void tud_cdc_line_coding_cb(uint8_t itf, cdc_line_coding_t const* coding)
{
	uart_init(true, coding->bit_rate);
}


/**
 * Other callbacks: if our UART isn't active, initialize it.
 */

void tud_cdc_rx_wanted_cb(uint8_t itf, char wanted_char)
{
	if (!uart_active) {
		uart_init(true, 115200);
	}
}

void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts)
{
	if (!uart_active) {
		uart_init(true, 115200);
	}
}
