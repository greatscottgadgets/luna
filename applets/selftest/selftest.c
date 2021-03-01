/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "platform.h"
#include "uart.h"
#include "ulpi.h"

// Create a type alias for our tests.
typedef bool (*simple_test)(void);


/**
 * Runs a named test.
 */
uint32_t run_test(char *description, simple_test test)
{
	// Identify which test we're running.
	uart_puts(description);

	// Run the test, and print its results.
	if (test()) {
		uart_puts("OK\n");
		return 0;
	} else {
		return 1;
	}
}



/**
 * Core tests.
 */
bool debug_controller_tests(void)
{
	return true;
}


/**
 * ULPI PHY tests.
 */
bool ulpi_phy_tests(enum ulpi_phy phy)
{
	uint8_t scratch;

	//
	// Check that the ULPI PHY matches the VID/PID for a Microchip USB3343.
	//
	const bool id_matches =
		(read_ulpi_register(phy, 0) == 0x24) &&
		(read_ulpi_register(phy, 1) == 0x04) &&
		(read_ulpi_register(phy, 2) == 0x09) &&
		(read_ulpi_register(phy, 3) == 0x00);
	if (!id_matches) {
		uart_puts("!!!!! PHY ID read failure! ");
		return false;
	}

	//
	// Check that we can set the scratch register to every binary-numbered value.
	// This checks each of the lines connected to the scratch register.
	//
	for (uint16_t i = 0; i < 8; i++) {
		uint8_t mask = (1 << i);

		// Perform a write followed by a read, to make sure the write took.
		write_ulpi_register(phy, 0x16, mask);
		scratch = read_ulpi_register(phy, 0x16);

		if (scratch != mask) {
			uart_puts("!!!!! Scratch register readback failure (bit ");
			print_char('0' + i);
			uart_puts(" should have been ");
			uart_print_byte(mask);
			uart_puts(" but was ");
			uart_print_byte(scratch);
			uart_puts(")!\n");
			return false;
		}
	}

	return true;
}


bool target_phy_tests(void)
{
	return ulpi_phy_tests(TARGET_PHY);
}

bool host_phy_tests(void)
{
	return ulpi_phy_tests(HOST_PHY);
}

bool sideband_phy_tests(void)
{
	return ulpi_phy_tests(SIDEBAND_PHY);
}


/**
 * RAM tests.
 */
bool ram_tests(void)
{
	uart_puts("!!!!! Not yet implemented!\n");
	return false;
}

/**
 * Identifies itself to the user.
 */
void print_greeting(void)
{
	uart_puts("\n _     _   _ _   _   ___  \n");
	uart_puts("| |   | | | | \\ | | / _ \\ \n");
	uart_puts("| |   | | | |  \\| |/ /_\\ \\\n");
	uart_puts("| |   | | | | . ` ||  _  |\n");
	uart_puts("| |___| |_| | |\\  || | | |\n");
	uart_puts("\\_____/\\___/\\_| \\_/\\_| |_/\n\n\b");

	uart_puts("Self-test firmware booted.\n");
	uart_puts("Running on a Minerva RISC-V softcore.\n\n");
}


/**
 * Core self-test routine.
 */
int main(void)
{
	uint32_t failures = 0;

	// Perform our platform initialization.
	platform_bringup();

	// Wait for a bit, so we know the other side is listening and ready.
	// TODO: replace this with a simple command interface, so we don't have to wait?
	sleep_ms(1000);

	// Print a nice header for our tests.
	print_greeting();

	// Run our core tests.
	failures += run_test("Debug controller & communications:     ", debug_controller_tests);
	failures += run_test("Target ULPI PHY:                       ", target_phy_tests);
	failures += run_test("Host ULPI PHY:                         ", host_phy_tests);
	failures += run_test("Sideband ULPI PHY:                     ", sideband_phy_tests);

	uart_puts("\n\n");

	if (failures) {
		uart_puts("--------------- TESTS FAILED! ------------------\n");
		uart_puts("--------------- TESTS FAILED! ------------------\n");
		uart_puts("--------------- TESTS FAILED! ------------------\n");
	}
	else {
		uart_puts("All tests passed.\n\n");
	}

	while(1);
}

