/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#pragma once
#include "resources.h"

/**
 * Sleeps for the provided number of milliseconds.
 */
void sleep_ms(uint16_t milliseconds);


/**
 * Performs initial platform bringup.
 */
void platform_bringup(void);
