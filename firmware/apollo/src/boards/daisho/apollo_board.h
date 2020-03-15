/**
 * Apollo board definitions for LUNA hardware.
 * This file is part of LUNA.
 */

#ifndef __APOLLO_BOARD_H__
#define __APOLLO_BOARD_H__

#include <chip.h>
#include <inttypes.h>
#include <stdbool.h>

/**
 * Simple-but-hacky macros that allow us to treat a GPIO pin as a single object.
 * Takes on some nastiness here to hide some of the vendor-library nastiness.
 */
#define _DAISHO_GPIO(port, pin)  ((uint16_t)port << 8) | pin
#define _DAISHO_PORT(gpio)       (gpio >> 8)
#define _DAISHO_PIN(gpio)        (gpio & 0xFF)

// Create a quick alias for a GPIO type.
typedef uint16_t gpio_t;


/**
 * GPIO pins for each of the microcontroller LEDs.
 */
typedef enum {
	LED_STATUS = _DAISHO_GPIO(0, 1)
} led_t;


/**
 * Debug SPI pin locations.
 */
enum {
	PIN_SCK      = _DAISHO_GPIO(1, 15),
	PIN_SDI      = _DAISHO_GPIO(1, 22),
	PIN_SDO      = _DAISHO_GPIO(0, 22),
	PIN_FPGA_CS  = _DAISHO_GPIO(1, 19),
};


/**
 * GPIO pin numbers for each of the JTAG pins.
 */
enum {
	TDO_GPIO = _DAISHO_GPIO(1, 21),
	TDI_GPIO = _DAISHO_GPIO(0, 21),
	TCK_GPIO = _DAISHO_GPIO(1, 20),
	TMS_GPIO = _DAISHO_GPIO(1, 23),
};



/**
 * GPIO abstractions; hide vendor code.
 */
enum {
	GPIO_DIRECTION_IN  = 0,
	GPIO_DIRECTION_OUT = 1,

	GPIO_PULL_OFF = 0,
	GPIO_PIN_FUNCTION_OFF = 0,
};


static inline void gpio_set_pin_level(uint16_t pin, bool state)
{
	Chip_GPIO_SetPinState(LPC_GPIO, _DAISHO_PORT(pin), _DAISHO_PIN(pin), state);
}


static inline void gpio_toggle_pin_level(uint16_t pin)
{
	Chip_GPIO_SetPinToggle(LPC_GPIO, _DAISHO_PORT(pin), _DAISHO_PIN(pin));
}


static inline bool gpio_get_pin_level(uint16_t pin)
{
	return Chip_GPIO_GetPinState(LPC_GPIO, _DAISHO_PORT(pin), _DAISHO_PIN(pin));
}


static inline void gpio_set_pin_direction(uint16_t pin, bool direction)
{
	Chip_GPIO_SetPinDIR(LPC_GPIO, _DAISHO_PORT(pin), _DAISHO_PIN(pin), direction);
}


static inline void gpio_set_pin_pull_mode(uint16_t pin, uint8_t any)
{
	// TODO: do we want to do anything here, on Daisho?
}


static inline void gpio_set_pin_function(uint16_t pin, uint8_t any)
{
	// TODO: do we want to do anything here, on Daisho?
}




#endif
