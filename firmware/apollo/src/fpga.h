/**
 * Code for basic FPGA interfacing.
 * This file is part of LUNA.
 */

#ifndef __FPGA_H__
#define __FPGA_H__

/**
 * Sets up the I/O pins needed to configure the FPGA.
 */
void fpga_io_init(void);

/**
 * Requests that the FPGA clear its configuration and try to reconfigure.
 */
void trigger_fpga_reconfiguration(void);


#endif
