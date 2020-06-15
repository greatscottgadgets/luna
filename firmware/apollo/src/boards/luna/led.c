/*
 * LED control abstraciton code.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */


#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include <tusb.h>
#include <sam.h>
#include <bsp/board.h>
#include <hal/include/hal_gpio.h>


#include "led.h"


/** Store the current LED blink pattern. */
static blink_pattern_t blink_pattern = BLINK_IDLE;


/**
 * Sets the active LED blink pattern.
 */
void led_set_blink_pattern(blink_pattern_t pattern)
{
	blink_pattern = pattern;
	leds_off();
}


/**
 * Sets up each of the LEDs for use.
 */
void led_init(void)
{
	uint8_t pins[] = { LED_A, LED_B, LED_C, LED_D, LED_E };

	// Default each LED to an output and _off_.
	for (unsigned i = 0; i < LED_COUNT; ++i) {
		gpio_set_pin_direction(pins[i], GPIO_DIRECTION_OUT);
		gpio_set_pin_level(pins[i], true);
	}
}


/**
 * Turns the provided LED on.
 */
void led_on(led_t led)
{
	gpio_set_pin_level(led, false);
}


/**
 * Turns the provided LED off.
 */
void led_off(led_t led)
{
	gpio_set_pin_level(led, true);
}


/**
 * Toggles the provided LED.
 */
void led_toggle(led_t led)
{
	gpio_toggle_pin_level(led);
}


/**
 * Sets whether a given led is on.
 */
void led_set(led_t led, bool on)
{
	gpio_set_pin_level(led, !on);
}


/**
 * Turns off all of the device's LEDs.
 */
void leds_off(void)
{
  led_t leds[] = {LED_A, LED_B, LED_C, LED_D, LED_E};

  for (unsigned i = 0; i < 5; ++i) {
    led_off(leds[i]);
  }
}


/**
 * Turns on the given LED.
 */
static void display_led_number(uint8_t number)
{
  led_t leds[] = {LED_A, LED_B, LED_C, LED_D, LED_E};

  if (number < 5) {
    led_on(leds[number]);
  }
}


/**
 * Task that handles blinking the heartbeat LED.
 */
void heartbeat_task(void)
{
  static uint32_t start_ms = 0;
  static uint8_t active_led = 0;
  static bool count_up = true;

  // Blink every interval ms
  if ( board_millis() - start_ms < blink_pattern) return; // not enough time
  start_ms += blink_pattern;

  switch (blink_pattern) {

    // Standard blink pattern for when the device is idle.
    // Indicates that the device's JTAG lines are un-pulled.
    case BLINK_IDLE:
      led_toggle(LED_E);
      break;

    // Blink patterns for when the device is being used for JTAG
    // operation. When these are on, the uC is driving the JTAG lines,
    // so the JTAG header probably shouldn't used to drive the lines.
    case BLINK_JTAG_CONNECTED:
    case BLINK_JTAG_UPLOADING:

      // Sweep back and forth.
      if (active_led == 0xFF) {
        count_up = true;
      }
      if (active_led == 4) {
        count_up = false;
      }
      active_led = count_up ? active_led + 1  : active_led - 1;

      leds_off();
      display_led_number(active_led);
      display_led_number(active_led + 1);

      break;

    // Blink patterns for when the device is being used for SPI flash access.
    // When these are displayed,
    case BLINK_FLASH_CONNECTED:

      if (active_led == 5) {
        active_led = 0;
      }

      leds_off();
      display_led_number(active_led++);

      break;

  }
}
