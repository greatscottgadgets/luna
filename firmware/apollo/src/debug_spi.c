/**
 * Interface code for communicating with the FPGA over the Debug SPI connection.
 * This file is part of LUNA.
 */

#include <tusb.h>
#include <hal/include/hal_gpio.h>
#include <bsp/board.h>

#include "spi.h"
#include "led.h"
#include "uart.h"

// Selects whether we should use the SAMD SERCOM for SPI.
// To select arbitrary pins for the SPI bus, uncomment this to use bitbang SPI.
//#define USE_SERCOM_FOR_SPI

/**
 * Pin locations for the debug SPI connection.
 * Used when using bitbang mode for the debug SPI.
 */

#if (_BOARD_REVISION_MAJOR_ == 0) && (_BOARD_REVISION_MINOR_ == 1)

enum {
	PIN_SCK      = PIN_PA00,

	PIN_SDI      = PIN_PA12,
	PIN_SDO      = PIN_PA14,

	PIN_FPGA_CS  = PIN_PA01,
	PIN_FLASH_CS = PIN_PA04
};

#else


enum {
	PIN_SCK      = PIN_PA13,

	PIN_SDI      = PIN_PA12,
	PIN_SDO      = PIN_PA14,

	PIN_FPGA_CS  = PIN_PA15,
	PIN_FLASH_CS = PIN_PA04
};


#endif


// SPI comms buffers.
// TODO: should these be unified into a single general buffer for requests,
// for e.g. the smaller SAMD11?
// 256 + 4 fits a SPI flash page and command
static uint8_t spi_in_buffer[256 + 4];
static uint8_t spi_out_buffer[256 + 4];

#ifdef USE_SERCOM_FOR_SPI

/**
 * Set up the debug SPI configuration.
 */
void debug_spi_init(void)
{
	spi_init(SPI_FPGA_DEBUG, false, true, 100, 0, 0);
}


/**
 * Send data over the debug SPI.
 */
static void debug_spi_send(void *data_to_send, void *data_to_receive, length)
{
	spi_send(SPI_FPGA_DEBUG, data_to_send, data_to_receive, length);
}


#else

/**
 * Set up the debug SPI configuration.
 */
void debug_spi_init(void)
{
	gpio_set_pin_function(PIN_SDI, GPIO_PIN_FUNCTION_OFF);
	gpio_set_pin_function(PIN_SCK, GPIO_PIN_FUNCTION_OFF);
	gpio_set_pin_function(PIN_SDO, GPIO_PIN_FUNCTION_OFF);
	gpio_set_pin_function(PIN_FPGA_CS,  GPIO_PIN_FUNCTION_OFF);

	gpio_set_pin_direction(PIN_SDI, GPIO_DIRECTION_OUT);
	gpio_set_pin_direction(PIN_SCK, GPIO_DIRECTION_OUT);
	gpio_set_pin_direction(PIN_SDO, GPIO_DIRECTION_IN);
	gpio_set_pin_direction(PIN_FPGA_CS,  GPIO_DIRECTION_OUT);

	gpio_set_pin_level(PIN_FPGA_CS, true);

	// Keep the configuration flash line as an input, but apply
	// a weak pull-up to keep the pin from being selected while idle.
	gpio_set_pin_direction(PIN_FLASH_CS, GPIO_DIRECTION_IN);
	gpio_set_pin_pull_mode(PIN_FLASH_CS, GPIO_PULL_UP);

}


static void half_bit_delay(void)
{
	for (unsigned i = 0; i < 10; ++i) {
		__NOP();
	}
}


/**
 * Transmits and receives a single bit over the debug SPI bus.
 *
 * @param bit_to_send True iff this SPI cycle should issue a logic '1'.
 * @return True iff the device provided a logic '1' to read.
 */
static bool debug_spi_exchange_bit(bool bit_to_send)
{
    bool value_read;

    // Scan out our new bit.
    gpio_set_pin_level(PIN_SDI, bit_to_send);

    // Create our rising edge.
	half_bit_delay();
    gpio_set_pin_level(PIN_SCK, true);

    // Read in the data on the SPI bus, and create our falling edge.
	half_bit_delay();
    value_read = gpio_get_pin_level(PIN_SDO);
    gpio_set_pin_level(PIN_SCK, false);

    return value_read;
}


/**
 * Sends and receives a single byte over our bitbanged SPI bus.
 */
static uint8_t debug_spi_exchange_byte(uint8_t to_send)
{
    uint8_t received = 0;

    for (unsigned i = 0; i < 8; ++i) {
        bool bit_to_send = (to_send & 0b10000000) ? 1 : 0;
        bool bit_received = debug_spi_exchange_bit(bit_to_send);

        // Add the newly received bit to our byte, and move forward in the byte to transmit/
        received = (received << 1) | (bit_received ? 1 : 0);
        to_send <<= 1;
    }

    return received;
}


/**
 * Transmits and receives a collection of bytes over the SPI bus.
 */
static void debug_spi_send(uint8_t *tx_buffer, uint8_t *rx_buffer, size_t length)
{
    for (size_t i = 0; i < length; ++i) {
        rx_buffer[i] = debug_spi_exchange_byte(tx_buffer[i]);
    }
}


#endif



/**
 * Request that sends a block of data over our debug SPI.
 * 	wValue: 0 = this transaction ends a transfer;
 *          1 = transaction will continue after
 *  wIndex: 0 = this transaction should be made with CS low;
 *          1 = this transaction should be made with CS high
 */
bool handle_debug_spi_send(uint8_t rhport, tusb_control_request_t const* request)
{
	// If we've been handed too much data, stall.
	if (request->wLength > sizeof(spi_out_buffer)) {
		return false;
	}

	// TODO: don't run this on r0.2+ boards?
	uart_release_pinmux();

	// Queue a transfer that will receive the relevant SPI data.
	// We'll perform the send itself once the data transfer is complete.
	return tud_control_xfer(rhport, request, spi_out_buffer, request->wLength);
}


bool handle_debug_spi_send_complete(uint8_t rhport, tusb_control_request_t const* request)
{
	// Use an active-low CS if wIndex isn't set; or an active-high one otherwise.
	bool cs_pin_active_level = request->wIndex ? true : false;

	gpio_set_pin_level(PIN_FPGA_CS, cs_pin_active_level);
	debug_spi_send(spi_out_buffer, spi_in_buffer, request->wLength);

	if (!request->wValue) {
		gpio_set_pin_level(PIN_FPGA_CS, !cs_pin_active_level);

		// To support multiplexing the CS line, if this is an active-high-CS transaction,
		// we'll pulse the cs_pin to its inactive level briefly, and then return CS
		// to its normal "idle-high".
		if (request->wIndex) {
			gpio_set_pin_level(PIN_FPGA_CS, true);
		}
	}

	return true;
}


/**
 * Request that changes the active LED pattern.
 */
bool handle_debug_spi_get_response(uint8_t rhport, tusb_control_request_t const* request)
{
	uint16_t length = request->wLength;

	// If the user has requested more data than we have, return only what we have.
	if (length > sizeof(spi_in_buffer)) {
		length = sizeof(spi_in_buffer);
	}

	// Send up the contents of our IN buffer.
	return tud_control_xfer(rhport, request, spi_in_buffer, length);
}


/**
 * Request that sends a block of data over our debug SPI.
 */
bool handle_flash_spi_send(uint8_t rhport, tusb_control_request_t const* request)
{
	// If we've been handed too much data, stall.
	if (request->wLength > sizeof(spi_out_buffer)) {
		return false;
	}

	// Queue a transfer that will receive the relevant SPI data.
	// We'll perform the send itself once the data transfer is complete.
	return tud_control_xfer(rhport, request, spi_out_buffer, request->wLength);
}


bool handle_flash_spi_send_complete(uint8_t rhport, tusb_control_request_t const* request)
{
	// Ensure that we're actively sending...
	gpio_set_pin_level(PIN_FLASH_CS, false);

	// ... send the data...
	debug_spi_send(spi_out_buffer, spi_in_buffer, request->wLength);

	// ... and end the tranmission, unless we've been instructed to keep the line open.
	if (!request->wValue) {
		gpio_set_pin_level(PIN_FLASH_CS, true);
	}

	return true;
}


/**
 * Request that grabs access to the configuration SPI lines.
 */
bool handle_take_configuration_spi(uint8_t rhport, tusb_control_request_t const* request)
{
	// Grab the SPI flash's CS pin...
	gpio_set_pin_level(PIN_FLASH_CS, true);

	gpio_set_pin_function(PIN_FLASH_CS,  GPIO_PIN_FUNCTION_OFF);
	gpio_set_pin_direction(PIN_FLASH_CS, GPIO_DIRECTION_OUT);

	// ... and set a blink pattern accordingly.
	led_set_blink_pattern(BLINK_FLASH_CONNECTED);
	return tud_control_xfer(rhport, request, NULL, 0);
}


/**
 * Request that releases access to the configuration SPI lines.
 */
bool handle_release_configuration_spi(uint8_t rhport, tusb_control_request_t const* request)
{
	// Release the CS line, and then drop the blink pattern back to idle..
	gpio_set_pin_direction(PIN_FLASH_CS, GPIO_DIRECTION_IN);
	gpio_set_pin_pull_mode(PIN_FLASH_CS, GPIO_PULL_UP);
	led_set_blink_pattern(BLINK_IDLE);

	return tud_control_xfer(rhport, request, NULL, 0);
}
