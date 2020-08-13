/**
 * Code for FPGA clock control.
 *
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <bsp/board.h>
#include <apollo_board.h>

// Clock configuration pins.
enum {
	PIN_CLOCKGEN_I2C_SCL       = _DAISHO_GPIO(0, 4),
	PIN_CLOCKGEN_I2C_SDA       = _DAISHO_GPIO(0, 5),

	PIN_CLOCKGEN_OUTPUT_ENABLE = _DAISHO_GPIO(1, 14)
};


// Clock configuration constants.
enum {
	SI5351C_I2C_ADDR   = 0x60,
};

/**
 * Sets up communications with Daisho's clock synthesizer.
 */
static void set_up_clockgen_communications(void)
{
	Chip_Clock_EnablePeriphClock(SYSCTL_CLOCK_I2C);

	// Bring up our I2C at a standard 100kHZ...
	Chip_I2CM_Init(LPC_I2C);
	Chip_I2CM_SetBusSpeed(LPC_I2C, 100000);
	Chip_I2CM_ResetControl(LPC_I2C);

	// ... and switch to our I2C pinmux functions.
	Chip_IOCON_PinMux(LPC_IOCON,
		_DAISHO_PORT(PIN_CLOCKGEN_I2C_SCL), _DAISHO_PIN(PIN_CLOCKGEN_I2C_SCL),
		 0, IOCON_FUNC1);
	Chip_IOCON_PinMux(LPC_IOCON,
		_DAISHO_PORT(PIN_CLOCKGEN_I2C_SDA), _DAISHO_PIN(PIN_CLOCKGEN_I2C_SDA),
		 0, IOCON_FUNC1);
}


/* write to single register */
void si5351c_write_single(uint8_t reg, uint8_t val)
{
	I2CM_XFER_T transfer = {
		.slaveAddr = SI5351C_I2C_ADDR,
		.options   = 0,
		.txSz      = 1,
		.rxSz      = 0,
		.txBuff    = &reg,
		.rxBuff    = NULL
	};

	Chip_I2CM_XferBlocking(LPC_I2C, &transfer);
}

/* read single register */
uint8_t si5351c_read_single(uint8_t reg)
{
	uint8_t val;

	I2CM_XFER_T transfer = {
		.slaveAddr = SI5351C_I2C_ADDR,
		.options   = 0,
		.txSz      = 1,
		.rxSz      = 1,
		.txBuff    = &reg,
		.rxBuff    = &val
	};

	Chip_I2CM_XferBlocking(LPC_I2C, &transfer);

	return val;
}

/*
 * Write to one or more contiguous registers. data[0] should be the first
 * register number, one or more values follow.
 */
void si5351c_write(uint8_t* const data, const uint_fast8_t data_count)
{
	I2CM_XFER_T transfer = {
		.slaveAddr = SI5351C_I2C_ADDR,
		.options   = 0,
		.txSz      = data_count,
		.rxSz      = 0,
		.txBuff    = data,
		.rxBuff    = NULL
	};

	Chip_I2CM_XferBlocking(LPC_I2C, &transfer);
}

/* Disable all CLKx outputs. */
void si5351c_disable_all_outputs(void)
{
	uint8_t data[] = { 3, 0xFF };
	si5351c_write(data, sizeof(data));
}

/* Turn off OEB pin control for all CLKx */
void si5351c_disable_oeb_pin_control(void)
{
	uint8_t data[] = { 9, 0xFF };
	si5351c_write(data, sizeof(data));
}

/* Power down all CLKx */
void si5351c_power_down_all_clocks(void)
{
	uint8_t data[] = { 16, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0xC0, 0xC0 };
	si5351c_write(data, sizeof(data));
}

/*
 * Register 183: Crystal Internal Load Capacitance
 * Reads as 0xE4 on power-up
 * Set to ???
 */
void si5351c_set_crystal_configuration(void)
{
	uint8_t data[] = { 183, 0b10100100 };
	si5351c_write(data, sizeof(data));
}

/*
 * Register 187: Fanout Enable
 * Turn on XO and MultiSynth fanout only.
 */
void si5351c_enable_xo_and_ms_fanout(void)
{
	uint8_t data[] = { 187, 0x50 };
	si5351c_write(data, sizeof(data));
}

/*
 * Register 15: PLL Input Source
 * CLKIN_DIV=0 (Divide by 1)
 * PLLB_SRC=0 (XTAL input)
 * PLLA_SRC=0 (XTAL input)
 */
void si5351c_configure_pll_sources_for_xtal(void)
{
	uint8_t data[] = { 15, 0x00 };
	si5351c_write(data, sizeof(data));
}

/* MultiSynth NA (PLL1) */
void si5351c_configure_pll1_multisynth(void)
{
	/* Multiply clock source by 32 */
	/* a = 32, b = 0, c = 1 */
	/* p1 = 0xe00, p2 = 0, p3 = 1 */
	uint8_t data[] = { 26, 0x00, 0x01, 0x00, 0x0E, 0x00, 0x00, 0x00, 0x00 };
	si5351c_write(data, sizeof(data));
}

void si5351c_configure_multisynth(const uint_fast8_t ms_number,
		const uint32_t p1, const uint32_t p2, const uint32_t p3,
    	const uint_fast8_t r_div)
{
	/*
	 * TODO: Check for p3 > 0? 0 has no meaning in fractional mode?
	 * And it makes for more jitter in integer mode.
	 */
	/*
	 * r is the r divider value encoded:
	 *   0 means divide by 1
	 *   1 means divide by 2
	 *   2 means divide by 4
	 *   ...
	 *   7 means divide by 128
	 */
	const uint_fast8_t register_number = 42 + (ms_number * 8);
	uint8_t data[] = {
			register_number,
			(p3 >> 8) & 0xFF,
			(p3 >> 0) & 0xFF,
			(r_div << 4) | (0 << 2) | ((p1 >> 16) & 0x3),
			(p1 >> 8) & 0xFF,
			(p1 >> 0) & 0xFF,
			(((p3 >> 16) & 0xF) << 4) | (((p2 >> 16) & 0xF) << 0),
			(p2 >> 8) & 0xFF,
			(p2 >> 0) & 0xFF };
	si5351c_write(data, sizeof(data));
}

void si5351c_configure_multisynths_6_and_7(void) {
	/* ms6_p1 = 6, ms7_pi1 = 6, r6_div = /1, r7_div = /1 */
	uint8_t ms6_7_data[] = { 90,
		0b00000110, 0b00000110,
		0b00000000
	};
	si5351c_write(ms6_7_data, sizeof(ms6_7_data));
}
/*
 * Registers 16 through 23: CLKx Control
 * CLK0:
 *   CLK0_PDN=1 (powered down)
 *   MS0_INT=1 (integer mode)
 * CLK1:
 *   CLK1_PDN=1 (powered down)
 *   MS1_INT=1 (integer mode)
 * CLK2:
 *   CLK2_PDN=1 (powered down)
 *   MS2_INT=1 (integer mode)
 * CLK3:
 *   CLK3_PDN=1 (powered down)
 *   MS3_INT=1 (integer mode)
 * CLK4:
 *   CLK4_PDN=0 (powered up)
 *   MS4_INT=1 (integer mode)
 *   MS4_SRC=0 (PLLA as source for MultiSynth 4)
 *   CLK4_INV=1 (inverted)
 *   CLK4_SRC=11 (MS4 as input source)
 *   CLK4_IDRV=11 (8mA)
 * CLK5:
 *   CLK5_PDN=0 (powered up)
 *   MS5_INT=1 (integer mode)
 *   MS5_SRC=0 (PLLA as source for MultiSynth 5)
 *   CLK5_INV=0 (not inverted)
 *   CLK5_SRC=10 (MS4 as input source)
 *   CLK5_IDRV=11 (8mA)
 * CLK6: (not connected)
 *   CLK6_PDN=0 (powered up)
 *   FBA_INT=1 (FBA MultiSynth integer mode)
 *   MS6_SRC=0 (PLLA as source for MultiSynth 6)
 *   CLK6_INV=1 (inverted)
 *   CLK6_SRC=10 (MS4 as input source)
 *   CLK6_IDRV=11 (8mA)
 * CLK7: (not connected)
 *   CLK7_PDN=0 (powered up)
 *   FBB_INT=1 (FBB MultiSynth integer mode)
 *   MS7_SRC=0 (PLLA as source for MultiSynth 7)
 *   CLK7_INV=0 (not inverted)
 *   CLK7_SRC=10 (MS4 as input source)
 *   CLK7_IDRV=11 (8mA)
 */
void si5351c_configure_clock_control(void)
{
	uint8_t data[] = { 16,
		0x80,
		0x80,
		0x80,
		0x80,
		0x5f,
		0x4b,
		0x5b,
		0x4b
	};
	si5351c_write(data, sizeof(data));
}

/* Enable CLK outputs 4, 5, 6, 7 only. */
void si5351c_enable_clock_outputs(void)
{
	uint8_t data[] = { 3, 0x0F };
	si5351c_write(data, sizeof(data));
}




/**
 * Sets up the board's clock synthesizer to provide the FPGA with a clock.
 */
void fpga_initialize_clocking(void)
{
	// Set up our I2C communcations with the clocking chip...
	set_up_clockgen_communications();
	board_delay(1000);

	si5351c_disable_all_outputs();
	si5351c_disable_oeb_pin_control();
	si5351c_power_down_all_clocks();
	si5351c_set_crystal_configuration();
	si5351c_enable_xo_and_ms_fanout();
	si5351c_configure_pll_sources_for_xtal();
	si5351c_configure_pll1_multisynth();

	si5351c_configure_multisynth(4, 1536, 0, 1, 0); // 50MHz
	si5351c_configure_multisynth(5, 1536, 0, 1, 0); // 50MHz
	si5351c_configure_multisynths_6_and_7();

	si5351c_configure_clock_control();
	si5351c_enable_clock_outputs();

	// Turn out the clock output buffers.
	gpio_set_pin_level(PIN_CLOCKGEN_OUTPUT_ENABLE, false);
}
