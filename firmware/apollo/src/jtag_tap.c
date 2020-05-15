/**
 * Code adapted from Arduino-JTAG;
 *    portions copyright (c) 2015 Marcelo Roberto Jimenez <marcelo.jimenez (at) gmail (dot) com>.
 *    portions copyright (c) 2019 Katherine J. Temkin <kate@ktemkin.com>
 *    portions copyright (c) 2019 Great Scott Gadgets <ktemkin@greatscottgadgets.com>
 */
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include <tusb.h>
#include <apollo_board.h>
#include <bsp/board.h>

#include <platform_jtag.h>

#include "led.h"
#include "jtag.h"

void jtag_state_ack(bool tms);

/*
 * Low nibble : TMS == 0
 * High nibble: TMS == 1
 */

#define TMS_T(TMS_HIGH_STATE, TMS_LOW_STATE) (((TMS_HIGH_STATE) << 4) | (TMS_LOW_STATE))

static const uint8_t tms_transitions[] = {
	/* STATE_TEST_LOGIC_RESET */ TMS_T(STATE_TEST_LOGIC_RESET, STATE_RUN_TEST_IDLE),
	/* STATE_RUN_TEST_IDLE    */ TMS_T(STATE_SELECT_DR_SCAN,   STATE_RUN_TEST_IDLE),
	/* STATE_SELECT_DR_SCAN   */ TMS_T(STATE_SELECT_IR_SCAN,   STATE_CAPTURE_DR),
	/* STATE_CAPTURE_DR       */ TMS_T(STATE_EXIT1_DR,         STATE_SHIFT_DR),
	/* STATE_SHIFT_DR         */ TMS_T(STATE_EXIT1_DR,         STATE_SHIFT_DR),
	/* STATE_EXIT1_DR         */ TMS_T(STATE_UPDATE_DR,        STATE_PAUSE_DR),
	/* STATE_PAUSE_DR         */ TMS_T(STATE_EXIT2_DR,         STATE_PAUSE_DR),
	/* STATE_EXIT2_DR         */ TMS_T(STATE_UPDATE_DR,        STATE_SHIFT_DR),
	/* STATE_UPDATE_DR        */ TMS_T(STATE_SELECT_DR_SCAN,   STATE_RUN_TEST_IDLE),
	/* STATE_SELECT_IR_SCAN   */ TMS_T(STATE_TEST_LOGIC_RESET, STATE_CAPTURE_IR),
	/* STATE_CAPTURE_IR       */ TMS_T(STATE_EXIT1_IR,         STATE_SHIFT_IR),
	/* STATE_SHIFT_IR         */ TMS_T(STATE_EXIT1_IR,         STATE_SHIFT_IR),
	/* STATE_EXIT1_IR         */ TMS_T(STATE_UPDATE_IR,        STATE_PAUSE_IR),
	/* STATE_PAUSE_IR         */ TMS_T(STATE_EXIT2_IR,         STATE_PAUSE_IR),
	/* STATE_EXIT2_IR         */ TMS_T(STATE_UPDATE_IR,        STATE_SHIFT_IR),
	/* STATE_UPDATE_IR        */ TMS_T(STATE_SELECT_DR_SCAN,   STATE_RUN_TEST_IDLE),
};

#define BITSTR(A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P) ( \
	((uint16_t)(A) << 15) | \
	((uint16_t)(B) << 14) | \
	((uint16_t)(C) << 13) | \
	((uint16_t)(D) << 12) | \
	((uint16_t)(E) << 11) | \
	((uint16_t)(F) << 10) | \
	((uint16_t)(G) <<  9) | \
	((uint16_t)(H) <<  8) | \
	((uint16_t)(I) <<  7) | \
	((uint16_t)(J) <<  6) | \
	((uint16_t)(K) <<  5) | \
	((uint16_t)(L) <<  4) | \
	((uint16_t)(M) <<  3) | \
	((uint16_t)(N) <<  2) | \
	((uint16_t)(O) <<  1) | \
	((uint16_t)(P) <<  0) )

/*
 * The index of this vector is the current state. The i-th bit tells you the
 * value TMS must assume in order to go to state "i".

------------------------------------------------------------------------------------------------------------
|                        |   || F | E | D | C || B | A | 9 | 8 || 7 | 6 | 5 | 4 || 3 | 2 | 1 | 0 ||   HEX  |
------------------------------------------------------------------------------------------------------------
| STATE_TEST_LOGIC_RESET | 0 || 0 | 0 | 0 | 0 || 0 | 0 | 0 | 0 || 0 | 0 | 0 | 0 || 0 | 0 | 0 | 1 || 0x0001 |
| STATE_RUN_TEST_IDLE    | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 0 | 1 || 0xFFFD |
| STATE_SELECT_DR_SCAN   | 2 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 0 || 0 | 0 | 0 | 0 || 0 | x | 1 | 1 || 0xFE03 |
| STATE_CAPTURE_DR       | 3 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 0 || x | 1 | 1 | 1 || 0xFFE7 |
| STATE_SHIFT_DR         | 4 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 0 || 1 | 1 | 1 | 1 || 0xFFEF |
| STATE_EXIT1_DR         | 5 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 0 | 0 | x | 0 || 1 | 1 | 1 | 1 || 0xFF0F |
| STATE_PAUSE_DR         | 6 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 0 | 1 | 1 || 1 | 1 | 1 | 1 || 0xFFBF |
| STATE_EXIT2_DR         | 7 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || x | 0 | 0 | 0 || 1 | 1 | 1 | 1 || 0xFF0F |
| STATE_UPDATE_DR        | 8 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | x || 1 | 1 | 1 | 1 || 1 | 1 | 0 | 1 || 0xFEFD |
| STATE_SELECT_IR_SCAN   | 9 || 0 | 0 | 0 | 0 || 0 | 0 | x | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 0x01FF |
| STATE_CAPTURE_IR       | A || 1 | 1 | 1 | 1 || 0 | x | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 0xF3FF |
| STATE_SHIFT_IR         | B || 1 | 1 | 1 | 1 || 0 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 0xF7FF |
| STATE_EXIT1_IR         | C || 1 | 0 | 0 | x || 0 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 0x87FF |
| STATE_PAUSE_IR         | D || 1 | 1 | 0 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 0xDFFF |
| STATE_EXIT2_IR         | E || 1 | x | 0 | 0 || 0 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 0x87FF |
| STATE_UPDATE_IR        | F || x | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 1 | 1 || 1 | 1 | 0 | 1 || 0x7FFD |
------------------------------------------------------------------------------------------------------------

*/
static const uint16_t tms_map[] = {
/* STATE_TEST_LOGIC_RESET */ BITSTR(  0, 0, 0, 0,   0, 0, 0, 0,   0, 0, 0, 0,   0, 0, 0, 1  ),
/* STATE_RUN_TEST_IDLE    */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 1,   1, 1, 0, 1  ),
/* STATE_SELECT_DR_SCAN   */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 0,   0, 0, 0, 0,   0, 0, 1, 1  ),
/* STATE_CAPTURE_DR       */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 0,   0, 1, 1, 1  ),
/* STATE_SHIFT_DR         */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 0,   1, 1, 1, 1  ),
/* STATE_EXIT1_DR         */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 1,   0, 0, 0, 0,   1, 1, 1, 1  ),
/* STATE_PAUSE_DR         */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 1,   1, 0, 1, 1,   1, 1, 1, 1  ),
/* STATE_EXIT2_DR         */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 1,   0, 0, 0, 0,   1, 1, 1, 1  ),
/* STATE_UPDATE_DR        */ BITSTR(  1, 1, 1, 1,   1, 1, 1, 0,   1, 1, 1, 1,   1, 1, 0, 1  ),
/* STATE_SELECT_IR_SCAN   */ BITSTR(  0, 0, 0, 0,   0, 0, 0, 1,   1, 1, 1, 1,   1, 1, 1, 1  ),
/* STATE_CAPTURE_IR       */ BITSTR(  1, 1, 1, 1,   0, 0, 1, 1,   1, 1, 1, 1,   1, 1, 1, 1  ),
/* STATE_SHIFT_IR         */ BITSTR(  1, 1, 1, 1,   0, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 1  ),
/* STATE_EXIT1_IR         */ BITSTR(  1, 0, 0, 0,   0, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 1  ),
/* STATE_PAUSE_IR         */ BITSTR(  1, 1, 0, 1,   1, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 1  ),
/* STATE_EXIT2_IR         */ BITSTR(  1, 0, 0, 0,   0, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 1  ),
/* STATE_UPDATE_IR        */ BITSTR(  0, 1, 1, 1,   1, 1, 1, 1,   1, 1, 1, 1,   1, 1, 0, 1  ),
};

static uint8_t current_state;

uint8_t jtag_current_state(void)
{
	return current_state;
}

void jtag_set_current_state(uint8_t state)
{
	current_state = state;
}


/**
 * Hook for any per-platform initialization that needs to occur.
 */
__attribute__((weak)) void jtag_platform_init(void)
{

}


/**
 * Hook for any per-platform deinitialization that needs to occur.
 */
__attribute__((weak)) void jtag_platform_deinit(void)
{

}


/**
 * Performs any start-of-day tasks necessary to talk JTAG to our FPGA.
 */
void jtag_init(void)
{
	gpio_set_pin_level(TCK_GPIO, false);

	// Set up each of our JTAG pins.
	gpio_set_pin_direction(TDO_GPIO, GPIO_DIRECTION_IN);
	gpio_set_pin_direction(TDI_GPIO, GPIO_DIRECTION_OUT);
	gpio_set_pin_direction(TCK_GPIO, GPIO_DIRECTION_OUT);
	gpio_set_pin_direction(TMS_GPIO, GPIO_DIRECTION_OUT);

	jtag_platform_init();
	jtag_set_current_state(STATE_TEST_LOGIC_RESET);
}


/**
 * De-inits the JTAG connection, so the JTAG chain. is no longer driven.
 */
void jtag_deinit(void)
{
	uint16_t gpio_pins[] = {
		TDO_GPIO, TDI_GPIO, TCK_GPIO, TMS_GPIO,
	};

	// Reset each of the JTAG pins to its unused state.
	// FIXME: apply the recommended pull resistors?
	for (unsigned i = 0; i < TU_ARRAY_SIZE(gpio_pins); ++i) {
		gpio_set_pin_direction(gpio_pins[i], GPIO_DIRECTION_IN);
		gpio_set_pin_pull_mode(gpio_pins[i], GPIO_PULL_OFF);
	}

	jtag_platform_deinit();
}





static inline void jtag_pulse_clock(void)
{
	gpio_set_pin_level(TCK_GPIO, false);
	__NOP();
	gpio_set_pin_level(TCK_GPIO, true);
}

static inline uint8_t jtag_pulse_clock_and_read_tdo(void)
{
	uint8_t ret;

	gpio_set_pin_level(TCK_GPIO, false);
	__NOP();
	ret = jtag_read_tdo();
	gpio_set_pin_level(TCK_GPIO, true);

	return ret;
}


void jtag_tap_shift(
	uint8_t *input_data,
	uint8_t *output_data,
	uint32_t data_bits,
	bool must_end)
{
	uint32_t bit_count = data_bits;
	uint32_t byte_count = (data_bits + 7) / 8;

	for (uint32_t i = 0; i < byte_count; ++i) {
		uint8_t byte_out = input_data[i];
		uint8_t tdo_byte = 0;
		for (int j = 0; j < 8 && bit_count-- > 0; ++j) {
			if (bit_count == 0 && must_end) {
				jtag_set_tms();
				jtag_state_ack(1);
			}
			if (byte_out & 1) {
				jtag_set_tdi();
			} else {
				jtag_clear_tdi();
			}
			byte_out >>= 1;
			bool tdo = jtag_pulse_clock_and_read_tdo();
			tdo_byte |= tdo << j;
		}
		output_data[i] = tdo_byte;
	}
}

void jtag_state_ack(bool tms)
{
	if (tms) {
		jtag_set_current_state((tms_transitions[jtag_current_state()] >> 4) & 0xf);
	} else {
		jtag_set_current_state(tms_transitions[jtag_current_state()] & 0xf);
	}
}

void jtag_state_step(bool tms)
{
	if (tms) {
		jtag_set_tms();
	} else {
		jtag_clear_tms();
	}

	board_delay(1);
	jtag_pulse_clock();
	jtag_state_ack(tms);
}

void jtag_go_to_state(unsigned state)
{
	if (state == STATE_TEST_LOGIC_RESET) {
		for (int i = 0; i < 5; ++i) {
			jtag_state_step(true);
		}
	} else {
		while (jtag_current_state() != state) {
			jtag_state_step((tms_map[jtag_current_state()] >> state) & 1);
		}
	}
}

void jtag_wait_time(uint32_t microseconds)
{
	while (microseconds--) {
		jtag_pulse_clock();
	}
}

