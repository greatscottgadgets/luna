/**
 * Platform-specific JTAG I/O helpers.
 * Using these rather than the raw GPIO functions allows read optimizations.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */


#ifndef __PLATFORM_JTAG_H__
#define __PLATFORM_JTAG_H__

#include <apollo_board.h>

// TODO: potentially optimize these?

static inline void jtag_set_tms(void)
{
	gpio_set_pin_level(TMS_GPIO, true);
}


static inline void jtag_clear_tms(void)
{
	gpio_set_pin_level(TMS_GPIO, false);
}


static inline void jtag_set_tdi(void)
{
	gpio_set_pin_level(TDI_GPIO, true);
}


static inline void jtag_clear_tdi(void)
{
	gpio_set_pin_level(TDI_GPIO, false);
}


static inline bool jtag_read_tdo(void)
{
	return gpio_get_pin_level(TDO_GPIO);
}

#endif
