/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#pragma once
#include "resources.h"

/**
 * Function pointer type for simple conditionals.
 */ 
typedef uint32_t (*simple_conditional)(void);


/**
 * Sleeps for the provided number of milliseconds.
 */
void sleep_ms(uint16_t milliseconds);

/**
 * Waits for a given conditional to be False, or for a given timeout to pass.
 * @returns 1 if the conditional timed out; or 0 otherwise
 */
int while_with_timeout(simple_conditional conditional, uint16_t timeout_ms);

/**
 * Performs initial platform bringup.
 */
void platform_bringup(void);
