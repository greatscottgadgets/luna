/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2021 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "platform.h"
#include "uart.h"
#include "ulpi.h"
#include "psram.h"

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
		uart_puts("✅ OK\n");
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
	int16_t scratch;

	//
	// Check that the ULPI PHY matches the VID/PID for a Microchip USB3343.
	//
	const bool id_matches =
		(read_ulpi_register(phy, 0) == 0x24) &&
		(read_ulpi_register(phy, 1) == 0x04) &&
		(read_ulpi_register(phy, 2) == 0x09) &&
		(read_ulpi_register(phy, 3) == 0x00);
	if (!id_matches) {
		uart_puts("❌ FAIL: PHY ID read failure! ");
		return false;
	}

	//
	// Check that we can set the scratch register to every binary-numbered value.
	// This checks each of the lines connected to the scratch register.
	//
	for (uint16_t i = 0; i < 8; i++) {
		uint8_t mask = (1 << i);

		// Perform a write followed by a read, to make sure the write took.
		//
		// For now, we seem to have an issue somwhere in timing that makes it
		// so these writes only take if multiply written. This doesn't affect actual
		// gateware, so for now, we're duplicating the writes.
		write_ulpi_register(phy, 0x16, mask);
		write_ulpi_register(phy, 0x16, mask);
		write_ulpi_register(phy, 0x16, mask);

		//write_ulpi_register(phy, 0x16, mask);
		scratch = read_ulpi_register(phy, 0x16);

		if (scratch != mask) {
			uart_puts("❌ FAIL: Scratch register readback failure (bit ");
			print_char('0' + i);
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
	//
	// Check that the ULPI PHY matches the VID/PID for a Winbond or Cypress PSRAM.
	//
	const uint32_t psram_id = read_psram_register(0);
	const bool id_matches = 
		(psram_id == 0x0c81) ||
		(psram_id == 0x0c86);


	if (psram_id == 0xFFFF) {
		uart_puts("❌ FAIL: RAM ID read failure! (RAM did not respond)\n");
		return false;
	}

	if (!id_matches) {
		uart_puts("❌ FAIL: RAM ID read failure! (was: ");
		uart_print_word(psram_id);
		uart_puts(")\n");
		return false;
	}

	return true;
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

	uart_puts("Self-test firmware booted. 🌙\n");
	uart_puts("Running on a Minerva RISC-V softcore on a ");
	uart_puts(PLATFORM_NAME);
	uart_puts(" board.\n\n");
}


/**
 * Core self-test routine.
 */
int main(void)
{
	uint32_t failures = 0;

	// Perform our platform initialization.
	platform_bringup();

	// Turn on the yellow LED, indicating that we're performing the tests.
	leds_output_write(0b001000);

	// Wait for a bit, so we know the other side is listening and ready.
	// FIXME: remove this?
	sleep_ms(1000);

	// Print a nice header for our tests.
	print_greeting();

	while (1) {
		char command = 0;

		//uart_puts("\n\n");
		//uart_puts("Press 's' to run the simple self-test (no connections required).");
		//uart_puts("Press 'f' to run the factory self-test (setup required).\n");
		//uart_puts("Press 'a' to run the full self-test (setup required).\n");
		//uart_puts("Press Ctrl+] to terminate test.\n");

		// FIXME: enable test switching

		// Wait for input from the user.
		//while (!command) {
		//	command = uart_getchar();
		//}
		command = 's';

		switch(command) {

			// Run all tests.
			case 'a':
				// Falls through.

			// Run factory tests.
			case 'f':
				// Falls through.

			// Run our core tests.
			case 's':
				command = 0;

				failures += run_test("Debug controller & communications:     ", debug_controller_tests);
				failures += run_test("Target ULPI PHY:                       ", target_phy_tests);
				failures += run_test("Host ULPI PHY:                         ", host_phy_tests);
				failures += run_test("Sideband ULPI PHY:                     ", sideband_phy_tests);
				failures += run_test("External RAM:                          ", ram_tests);

				uart_puts("\n\n");

				if (failures) {

					// Indicate our failure via serial...
					uart_puts("❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌\n");
					uart_puts("------------------------------------------------\n");
					uart_puts("--------------- TESTS FAILED! ------------------\n");
					uart_puts("------------------------------------------------\n");
					uart_puts("❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌❌\n");

					// ... and turn on the red LED.
					leds_output_write(0b100000);
				}
				
				else {
					// Indicate success, and turn on the green LED.
					leds_output_write(0b000100);
					uart_puts("All tests passed. ✅ \n\n");
				}

				// FIXME: remove this
				uart_puts("Press Ctrl+] to terminate test.\n");
				while(1);

				break;

			default:
				uart_puts("Unknown command.\n");
		}

	}
}

