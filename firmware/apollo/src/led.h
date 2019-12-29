/*
 * LED control abstraciton code.
 * This file is part of LUNA.
 */

#ifndef __LED_H__
#define __LED_H__

#include <sam.h>

// GPIO pins for each of the microcontroller LEDs.
typedef enum {
	LED_A = PIN_PA18, // Blue
	LED_B = PIN_PA19, // Pink
	LED_C = PIN_PA20, // White
	LED_D = PIN_PA21, // Pink
	LED_E = PIN_PA22, // Blue

	LED_COUNT = 5
} led_t;


/**
 * Different blink patterns with different semantic 
 */
typedef enum {
  BLINK_IDLE = 500,
  BLINK_JTAG_CONNECTED = 150,
  BLINK_JTAG_UPLOADING = 50,
} blink_pattern_t;



/**
 * Sets the active LED blink pattern.
 */
void led_set_blink_pattern(blink_pattern_t pattern);


/**
 * Sets up each of the LEDs for use.
 */
void led_init(void);


/**
 * Turns the provided LED on.
 */
void led_on(led_t led);


/**
 * Turns the provided LED off.
 */
void led_off(led_t led);


/**
 * Turns off all of the device's LEDs.
 */
void leds_off(void);


/**
 * Toggles the provided LED.
 */
void led_toggle(led_t led);


/**
 * Sets whether a given led is on.
 */
void led_set(led_t led, bool on);


/**
 * Task that handles blinking the heartbeat LED.
 */
void heartbeat_task(void);

#endif
