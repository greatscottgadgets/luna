/*
 * SPI driver code.
 * This file is part of LUNA.
 */

#include <sam.h>

#include <hpl/pm/hpl_pm_base.h>
#include <hpl/gclk/hpl_gclk_base.h>
#include <hal/include/hal_gpio.h>

#include "spi.h"
#include "led.h"

#include <bsp/board.h>


// Hide the ugly Atmel Sercom object name.
typedef Sercom sercom_t;

/**
 * Returns the SERCOM object associated with the given target.
 */
static sercom_t *sercom_for_target(spi_target_t target)
{
	switch (target) {
		case SPI_FPGA_JTAG:  return SERCOM0; // Alternatively, SERCOM2.
		case SPI_FPGA_DEBUG: return SERCOM2; // Alternatively, SERCOM4.
	}

	return NULL;
}


/**
 * Pinmux the relevent pins so the can be used for SERCOM SPI.
 */
static void _spi_configure_pinmux(spi_target_t target, bool use_for_spi)
{
	switch (target) {

		// FPGA JTAG connection -- configure PA08 (TDI), PA09 (TCK), and PA10 (TDO).
		case SPI_FPGA_JTAG:
			if (use_for_spi) {
				gpio_set_pin_function(PIN_PA08, MUX_PA08C_SERCOM0_PAD0);
				gpio_set_pin_function(PIN_PA09, MUX_PA09C_SERCOM0_PAD1);
				gpio_set_pin_function(PIN_PA10, MUX_PA10C_SERCOM0_PAD2);
			} else {
				gpio_set_pin_function(PIN_PA08, GPIO_PIN_FUNCTION_OFF);
				gpio_set_pin_function(PIN_PA09, GPIO_PIN_FUNCTION_OFF);
				gpio_set_pin_function(PIN_PA10, GPIO_PIN_FUNCTION_OFF);
			}
			break;

		// FPGA debug port -- configure PA12 (MOSI), PA13 (SCK), and PA14 (MISO) as SERCOM pins.
		case SPI_FPGA_DEBUG:
			if (use_for_spi) {
				gpio_set_pin_function(PIN_PA12, MUX_PA12C_SERCOM2_PAD0);
				gpio_set_pin_function(PIN_PA13, MUX_PA13C_SERCOM2_PAD1);
				gpio_set_pin_function(PIN_PA14, MUX_PA14C_SERCOM2_PAD2);
			} else {
				gpio_set_pin_function(PIN_PA12, GPIO_PIN_FUNCTION_OFF);
				gpio_set_pin_function(PIN_PA13, GPIO_PIN_FUNCTION_OFF);
				gpio_set_pin_function(PIN_PA14, GPIO_PIN_FUNCTION_OFF);
			}
			break;
	}
}


/**
 * Configures the relevant SPI target's pins to be used for SPI.
 */
void spi_configure_pinmux(spi_target_t target)
{
	_spi_configure_pinmux(target, true);
}


/**
 * Returns the relevant SPI target's pins to being used for GPIO.
 */
void spi_release_pinmux(spi_target_t target)
{
	_spi_configure_pinmux(target, false);
}


/**
 * Configures the clocking for the relevant SERCOM peripheral.
 */
static void spi_set_up_clocking(spi_target_t target)
{
	switch (target) {

		case SPI_FPGA_JTAG:
			_pm_enable_bus_clock(PM_BUS_APBC, SERCOM0);
			_gclk_enable_channel(SERCOM0_GCLK_ID_CORE, GCLK_CLKCTRL_GEN_GCLK0_Val);
			break;

		case SPI_FPGA_DEBUG:
			_pm_enable_bus_clock(PM_BUS_APBC, SERCOM2);
			_gclk_enable_channel(SERCOM2_GCLK_ID_CORE, GCLK_CLKCTRL_GEN_GCLK0_Val);
			break;
	}

	// Wait for the clock to be ready.
	while(GCLK->STATUS.bit.SYNCBUSY);
}


/**
 * Configures the provided target to be used as an SPI port via the SERCOM.
 */
void spi_init(spi_target_t target, bool lsb_first, bool configure_pinmux, uint8_t baud_divider,
	 uint8_t clock_polarity, uint8_t clock_phase)
{
	volatile sercom_t *sercom = sercom_for_target(target);

	// Disable the SERCOM before configuring it, to 1) ensure we're not transacting
	// during configuration; and 2) as many of the registers are R/O when the SERCOM is enabled.
	while(sercom->SPI.SYNCBUSY.bit.ENABLE);
	sercom->SPI.CTRLA.bit.ENABLE = 0;

	// Software reset the SERCOM to restore initial values.
	while(sercom->SPI.SYNCBUSY.bit.SWRST);
	sercom->SPI.CTRLA.bit.SWRST = 1;

	// The SWRST bit becomes accessible again once the software reset is
	// complete -- we'll use this to wait for the reset to be finshed.
	while(sercom->SPI.SYNCBUSY.bit.SWRST);

	// Ensure we can work with the full SERCOM.
	while(sercom->SPI.SYNCBUSY.bit.SWRST || sercom->SPI.SYNCBUSY.bit.ENABLE);

	// Pinmux the relevant pins to be used for the SERCOM.
	if (configure_pinmux) {
		spi_configure_pinmux(target);
	}

	// Set up clocking for the SERCOM peripheral.
	spi_set_up_clocking(target);

	// Configure the SERCOM for SPI master mode.
	sercom->SPI.CTRLA.reg =
		SERCOM_SPI_CTRLA_MODE_SPI_MASTER  |  // SPI master
		SERCOM_SPI_CTRLA_DOPO(0)          |  // use our first pin as MOSI, and our second at SCK
		SERCOM_SPI_CTRLA_DIPO(2)          |  // use our third pin as MISO
		(lsb_first ? SERCOM_SPI_CTRLA_DORD : 0);   // SPI byte order

	// Set the clock polarity and phase.
	sercom->SPI.CTRLA.bit.CPOL = clock_polarity;
	sercom->SPI.CTRLA.bit.CPHA = clock_phase;

	// Use the SPI transceiver.
	while(sercom->SPI.SYNCBUSY.bit.CTRLB);
	sercom->SPI.CTRLB.reg = SERCOM_SPI_CTRLB_RXEN;

	// Set the baud divider for the relevant channel.
	sercom->SPI.BAUD.reg = baud_divider;

	// Finally, enable the SPI controller.
	sercom->SPI.CTRLA.reg |= SERCOM_SPI_CTRLA_ENABLE;
	while(sercom->SPI.SYNCBUSY.bit.ENABLE);
}


/**
 * Synchronously send a single byte on the given SPI bus.
 * Does not manage the SSEL line.
 */
uint8_t spi_send_byte(spi_target_t port, uint8_t data)
{
	volatile sercom_t *sercom = sercom_for_target(port);

	// Send the relevant data...
	while(sercom->SPI.INTFLAG.bit.DRE == 0);
	sercom->SPI.DATA.reg = data;

	// ... and receive the response.
	while(sercom->SPI.INTFLAG.bit.RXC == 0);
	return (uint8_t)sercom->SPI.DATA.reg;
}


/**
 * Sends a block of data over the SPI bus.
 *
 * @param port The port on which to perform the SPI transaction.
 * @param data_to_send The data to be transferred over the SPI bus.
 * @param data_received Any data received during the SPI transaction.
 * @param length The total length of the data to be exchanged, in bytes.
 */
void spi_send(spi_target_t port, void *data_to_send, void *data_received, size_t length)
{
	uint8_t *to_send  = data_to_send;
	uint8_t *received = data_received;

	// TODO: use the FIFO to bulk send data
	for (unsigned i = 0; i < length; ++i) {
		received[i] = spi_send_byte(port, to_send[i]);
	}
}
