/**
 * Code for FPGA clock control.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

 #ifndef __FPGA_CLK_H__
 #define __FPGA_CLK_H__

/**
 * Sets up the board's clock synthesizer to provide the FPGA with a clock.
 */
void fpga_initialize_clocking(void);

 #endif
