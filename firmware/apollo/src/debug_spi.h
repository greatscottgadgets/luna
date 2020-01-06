/**
 * Interface code for communicating with the FPGA over the Debug SPI connection.
 * This file is part of LUNA.
 */

#ifndef __DEBUG_SPI_H__
#define __DEBUG_SPI_H__

#include <tusb.h>
#include <stdbool.h>

/**
 * Set up the debug SPI configuration.
 */
void debug_spi_init(void);

/**
 * Request that sends a block of data over SPI.
 */
bool handle_debug_spi_send(uint8_t rhport, tusb_control_request_t const* request);
bool handle_debug_spi_send_complete(uint8_t rhport, tusb_control_request_t const* request);

/**
 * Request that changes the active LED pattern.
 */
bool handle_debug_spi_get_response(uint8_t rhport, tusb_control_request_t const* request);

#endif
