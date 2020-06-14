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

static inline void jtag_set_tms(void)
{
	PORT_IOBUS->Group[0].OUTSET.reg = (1 << TMS_GPIO);
}


static inline void jtag_clear_tms(void)
{
	PORT_IOBUS->Group[0].OUTCLR.reg = (1 << TMS_GPIO);
}


static inline void jtag_set_tdi(void)
{
	PORT_IOBUS->Group[0].OUTSET.reg = (1 << TDI_GPIO);
}


static inline void jtag_clear_tdi(void)
{
	PORT_IOBUS->Group[0].OUTCLR.reg = (1 << TDI_GPIO);
}


static inline bool jtag_read_tdo(void)
{
	return PORT_IOBUS->Group[0].IN.reg & (1 << TDO_GPIO);
}

#endif
