/*
 * SPI driver code.
 * This file is part of LUNA.
 */

#ifndef __SPI_H__
#define __SPI_H__

typedef enum {
	 SPI_FPGA_JTAG,
	 SPI_FPGA_DEBUG
 } spi_target_t;


// Hide the ugly Atmel Sercom object name.
typedef Sercom sercom_t;


/**
 * Configures the relevant SPI target's pins to be used for SPI.
 */
void spi_configure_pinmux(spi_target_t target);


/**
 * Returns the relevant SPI target's pins to being used for GPIO.
 */
void spi_release_pinmux(spi_target_t target);


/**
 * Configures the provided target to be used as an SPI port via the SERCOM.
 */
void spi_init(spi_target_t target, bool lsb_first, bool configure_pinmux);


/**
 * Synchronously send a single byte on the given SPI bus.
 * Does not manage the SSEL line.
 */
uint8_t spi_send_byte(spi_target_t port, uint8_t data);


/**
 * Sends a block of data over the SPI bus.
 */
void spi_send(spi_target_t port, void *data_in, void *data_out, size_t length);

#endif
