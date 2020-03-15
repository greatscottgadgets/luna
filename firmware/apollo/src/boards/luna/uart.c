/**
 * UART driver code.
 * This file is part of LUNA.
 */


#include <sam.h>

#include <hpl/pm/hpl_pm_base.h>
#include <hpl/gclk/hpl_gclk_base.h>
#include <hal/include/hal_gpio.h>

#include <peripheral_clk_config.h>


// Hide the ugly Atmel Sercom object name.
typedef Sercom sercom_t;


// Create a quick reference to our SERCOM object.
static sercom_t *sercom = SERCOM1;

// Keep track of whether our UART has been configured and is active.
bool uart_active = false;


/**
 * Pinmux the relevent pins so the can be used for SERCOM UART.
 */
static void _uart_configure_pinmux(bool use_for_uart)
{
	if (use_for_uart) {
		gpio_set_pin_function(PIN_PA00, MUX_PA00D_SERCOM1_PAD0);
		gpio_set_pin_function(PIN_PA01, MUX_PA01D_SERCOM1_PAD1);
	} else {
		gpio_set_pin_function(PIN_PA00, GPIO_PIN_FUNCTION_OFF);
		gpio_set_pin_function(PIN_PA01, GPIO_PIN_FUNCTION_OFF);
	}
}


/**
 * Configures the relevant UART's target's pins to be used for UART.
 */
void uart_configure_pinmux(void)
{
	_uart_configure_pinmux(true);
	uart_active = true;
}


/**
 * Releases the relevant pins from being used for UART, returning them
 * to use as GPIO.
 */
void uart_release_pinmux(void)
{
	_uart_configure_pinmux(false);
	uart_active = false;
}


/**
 * Configures the UART we'll use for our system console.
 * TODO: support more configuration (parity, stop, etc.)
 */
void uart_init(bool configure_pinmux, unsigned long baudrate)
{
	// Disable the SERCOM before configuring it, to 1) ensure we're not transacting
	// during configuration; and 2) as many of the registers are R/O when the SERCOM is enabled.
	while(sercom->USART.SYNCBUSY.bit.ENABLE);
	sercom->USART.CTRLA.bit.ENABLE = 0;

	// Software reset the SERCOM to restore initial values.
	while(sercom->USART.SYNCBUSY.bit.SWRST);
	sercom->USART.CTRLA.bit.SWRST = 1;

	// The SWRST bit becomes accessible again once the software reset is
	// complete -- we'll use this to wait for the reset to be finshed.
	while(sercom->USART.SYNCBUSY.bit.SWRST);

	// Ensure we can work with the full SERCOM.
	while(sercom->USART.SYNCBUSY.bit.SWRST || sercom->USART.SYNCBUSY.bit.ENABLE);

	// Pinmux the relevant pins to be used for the SERCOM.
	if (configure_pinmux) {
		uart_configure_pinmux();
	}

	// Set up clocking for the SERCOM peripheral.
	_pm_enable_bus_clock(PM_BUS_APBC, SERCOM1);
	_gclk_enable_channel(SERCOM1_GCLK_ID_CORE, GCLK_CLKCTRL_GEN_GCLK0_Val);

	// Configure the SERCOM for UART mode.
	sercom->USART.CTRLA.reg =
		SERCOM_USART_CTRLA_DORD            |  // LSB first
		SERCOM_USART_CTRLA_TXPO(0)         |  // TX on PA00
		SERCOM_USART_CTRLA_RXPO(1)         |  // RX on PA01
		SERCOM_USART_CTRLA_SAMPR(0)        |  // use 16x oversampling
		SERCOM_USART_CTRLA_RUNSTDBY        |  // don't autosuspend the clock
		SERCOM_USART_CTRLA_MODE_USART_INT_CLK; // use internal clock

	// Configure our baud divisor.
	// From Atmel:
	float baud = 65536 * (float)(CONF_CPU_FREQUENCY - 16 * baudrate) / (float)CONF_CPU_FREQUENCY;
	sercom->USART.BAUD.reg = baud;

	// Configure TX/RX and framing.
	sercom->USART.CTRLB.reg =
			SERCOM_USART_CTRLB_CHSIZE(0) | // 8-bit words
			SERCOM_USART_CTRLB_TXEN      | // Enable TX.
			SERCOM_USART_CTRLB_RXEN;       // Enable RX.


	// Wait for our changes to apply.
	while (sercom->USART.SYNCBUSY.bit.CTRLB);

	// Enable our receive interrupt, as we want to asynchronously dump data into
	// the UART console.
	sercom->USART.INTENSET.reg = SERCOM_USART_INTENSET_RXC;

	// Enable the UART IRQ.
	NVIC_EnableIRQ(SERCOM1_IRQn);

	// Finally, enable the SERCOM.
	sercom->USART.CTRLA.bit.ENABLE = 1;
	while(sercom->USART.SYNCBUSY.bit.ENABLE);

}


/**
 * Callback issued when the UART recieves a new byte.
 */
__attribute__((weak)) void uart_byte_received_cb(uint8_t byte) {}


/**
 * UART interrupt handler.
 */
void SERCOM1_Handler(void)
{
	// If we've just received a character, handle it.
	if (sercom->USART.INTFLAG.bit.RXC)
	{
		// Read the relevant character, which marks this interrupt
		// as serviced.
		uint16_t byte = sercom->USART.DATA.reg;
		uart_byte_received_cb(byte);
	}
}



/**
 * @return True iff the UART can accept data.
 */
bool uart_ready_for_write(void)
{
	return (sercom->USART.INTFLAG.reg & SERCOM_USART_INTFLAG_DRE);
}


/**
 * Starts a write over the Apollo console UART.

 * Does not check for readiness; it is assumed the caller knows that the
 * UART is avaiable (e.g. by calling uart_ready_for_write).
 */
void uart_nonblocking_write(uint8_t byte)
{
	sercom->USART.DATA.reg = byte;
}



/**
 * Writes a byte over the Apollo console UART.
 *
 * @param byte The byte to be written.
 */
void uart_blocking_write(uint8_t byte)
{
	while(!uart_ready_for_write());
	uart_nonblocking_write(byte);
}
