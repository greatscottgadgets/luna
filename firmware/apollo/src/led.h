/*
 * LED control abstraciton code.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2019-2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef __LED_H__
#define __LED_H__

#include <apollo_board.h>

/**
 * Different blink patterns with different semantic meanings.
 */
typedef enum {
  BLINK_IDLE = 500,
  BLINK_JTAG_CONNECTED = 150,
  BLINK_JTAG_UPLOADING = 50,

  BLINK_FLASH_CONNECTED = 130,
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
