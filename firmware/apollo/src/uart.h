/**
 * UART driver code.
 * This file is part of LUNA.
 */

#ifndef __UART_H__
#define __UART_H__


/**
 * Configures the UART we'll use for our system console.
 *
 * @param configure_pinmux If true, the pinmux will be configured for UART use during init.
 * @param baudrate The baud rate to apply, in symbols/second.
 */
void uart_init(bool configure_pinmux, unsigned long baudrate);

/**
 * Configures the relevant UART's target's pins to be used for UART.
 */
void uart_configure_pinmux(void);


/**
 * Releases the relevant pins from being used for UART, returning them
 * to use as GPIO.
 */
void uart_release_pinmux(void);



/**
 * Writes a byte over the Apollo console UART.
 *
 * @param byte The byte to be written.
 */
void uart_blocking_write(uint8_t byte);


/**
 * @return True iff the UART can accept data.
 */
bool uart_ready_for_write(void);


/**
 * Starts a write over the Apollo console UART.

 * Does not check for readiness; it is assumed the caller knows that the
 * UART is available (e.g. by calling uart_ready_for_write).
 */
void uart_nonblocking_write(uint8_t byte);



#endif
