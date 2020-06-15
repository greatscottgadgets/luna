/**
 * Interface code for communicating with the FPGA over the Debug SPI connection.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
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
 * Requests that sends a block of data over SPI to the configuration flash.
 */
bool handle_flash_spi_send(uint8_t rhport, tusb_control_request_t const* request);
bool handle_flash_spi_send_complete(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Request that reads the result of the last {debug, flash} SPI transfer.
 */
bool handle_debug_spi_get_response(uint8_t rhport, tusb_control_request_t const* request);


/**
 * Request that grabs access to the configuration SPI lines.
 */
bool handle_take_configuration_spi(uint8_t rhport, tusb_control_request_t const* request);

/*
 * Request that releases access to the configuration SPI lines.
 */
bool handle_release_configuration_spi(uint8_t rhport, tusb_control_request_t const* request);


#endif
