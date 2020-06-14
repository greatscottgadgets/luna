/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <stdbool.h>

// Include our automatically generated resource file.
// This allows us to work with e.g. our registers no matter gt
#include "resources.h"


int main(void)
{
	bool shifting_right = true;
	uint8_t led_value = 0b110000;

	// Set up our timer to periodically move the LEDs.
	timer_en_write(1);
	timer_reload_write(0x0C0000);

	// And blink our LEDs.
	while(1) {

		// Skip all iterations that aren't our main one...
		if (timer_ctr_read()) {
			continue;
		}

		// ... compute our pattern ...
		if (shifting_right) {
			led_value >>= 1;

			if (led_value == 0b000011) {
				shifting_right = false;
			}
		} else {
			led_value <<= 1;

			if (led_value == 0b110000) {
				shifting_right = true;
			}

		}

		// ... and output it to the LEDs.
		leds_output_write(led_value);
	}
}
