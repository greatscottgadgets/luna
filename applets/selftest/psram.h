/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#pragma once

#include "resources.h"

/**
 * Reads a value from a ULPI PHY register.
 */
uint32_t read_psram_register(uint32_t address);
