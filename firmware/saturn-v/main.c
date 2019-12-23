// Copyright 2019 Katherine J. Temkin <kate@ktemkin.com>
// Copyright 2019 Great Scott Gadgets <ktemkin@greatscottgadgets.com>
// Copyright 2014 Technical Machine, Inc. See the COPYRIGHT
// file at the top-level directory of this distribution.
//
// Licensed under the Apache License, Version 2.0 <LICENSE-APACHE or
// http://www.apache.org/licenses/LICENSE-2.0> or the MIT license
// <LICENSE-MIT or http://opensource.org/licenses/MIT>, at your
// option. This file may not be copied, modified, or distributed
// except according to those terms.

#include "common/util.h"
#include "samd/usb_samd.h"

#include <string.h>
#include <stdbool.h>

#include "boot.h"
#include "common/nvm.h"


// Buttons.
const static Pin DFU_BUTTON = {.group = 1, .pin = 11, .mux = 0 };
const static Pin RECOVERY_BUTTON = {.group = 1, .pin = 22, .mux = 0 };

// LEDs.
const static Pin LED_PIN = {.group = 0, .pin = 18, .mux = 0 };

__attribute__ ((section(".copyright")))
__attribute__ ((used))
const char copyright_note[] = COPYRIGHT_NOTE;

volatile bool exit_and_jump = 0;

// set at runtime
uint32_t total_flash_size;

/*** SysTick ***/

volatile uint32_t g_msTicks;

/* SysTick IRQ handler */
void SysTick_Handler(void) {
	g_msTicks++;
}

void delay_ms(unsigned ms) {
	unsigned start = g_msTicks;
	while (g_msTicks - start <= ms) {
		__WFI();
	}
}

void init_systick(void) {
	if (SysTick_Config(48000000 / 1000)) {	/* Setup SysTick Timer for 1 msec interrupts  */
		while (1) {}								/* Capture error */
	}
	NVIC_SetPriority(SysTick_IRQn, 0x0);
	g_msTicks = 0;
}

/*** USB / DFU ***/

void dfu_cb_dnload_block(uint16_t block_num, uint16_t len) {
	if (usb_setup.wLength > DFU_TRANSFER_SIZE) {
		dfu_error(DFU_STATUS_errUNKNOWN);
		return;
	}

	if (block_num * DFU_TRANSFER_SIZE > FLASH_FW_SIZE) {
		dfu_error(DFU_STATUS_errADDRESS);
		return;
	}

	nvm_erase_row(FLASH_FW_START + block_num * DFU_TRANSFER_SIZE);
}

void dfu_cb_dnload_packet_completed(uint16_t block_num, uint16_t offset, uint8_t* data, uint16_t length) {
	unsigned addr = FLASH_FW_START + block_num * DFU_TRANSFER_SIZE + offset;
	nvm_write_page(addr, data, length);
}

unsigned dfu_cb_dnload_block_completed(uint16_t block_num, uint16_t length) {
	return 0;
}

void dfu_cb_manifest(void) {
	exit_and_jump = 1;
}

void noopFunction(void)
{
	// Placeholder function for code that isn't needed. Keep empty!
}

static void hardware_detect(void)
{
	// what kind of chip are we installed on?
	// .. don't care

	// how big is the flash tho
	uint16_t page_size = 1 << (NVMCTRL->PARAM.bit.PSZ + 3);

	total_flash_size = NVMCTRL->PARAM.bit.NVMP * page_size;
}

void bootloader_main(void)
{
	hardware_detect();

	// Turn on the LED that indicates we're in bootloader mode.
	pin_out(LED_PIN);
	pin_low(LED_PIN);

	// Set up the main clocks.
	clock_init_usb(GCLK_SYSTEM);
	init_systick();
	nvm_init();
	
	__enable_irq();

	pin_mux(PIN_USB_DM);
	pin_mux(PIN_USB_DP);
	usb_init();
	usb_attach();

	// Blink while we're in DFU mode.
	while(!exit_and_jump) {
		pin_high(LED_PIN);
		delay_ms(300);
		pin_low(LED_PIN);
		delay_ms(300);
	}

	delay_ms(25);

	usb_detach();
	nvm_invalidate_cache();

	delay_ms(100);

	// Hook: undo any special setup that board_setup_late might be needed to
	// undo the setup the bootloader code has done.
	NVIC_SystemReset();
}

bool flash_valid() {
	unsigned sp = ((unsigned *)FLASH_FW_ADDR)[0];
	unsigned ip = ((unsigned *)FLASH_FW_ADDR)[1];

	return     sp > 0x20000000
			&& ip >= 0x00001000
			&& ip <  0x00400000;
}

bool bootloader_sw_triggered(void)
{
	// Was reset caused by watchdog timer (WDT)?
	return PM->RCAUSE.reg & PM_RCAUSE_WDT;
}


bool button_pressed(void)
{
	pin_in(DFU_BUTTON);
	pin_in(RECOVERY_BUTTON);
	pin_pull_up(DFU_BUTTON);
	pin_pull_up(RECOVERY_BUTTON);


	// For now, either DFU or recovery should put the device into DFU mode.
	// Later, this should only be recovery.
	if (pin_read(DFU_BUTTON) == 0) {
		return true;
	}
	if (pin_read(RECOVERY_BUTTON) == 0) {
		return true;
	}

	return false;
}




void main_bl(void) {
	if (!flash_valid() || button_pressed() || bootloader_sw_triggered()) {
		bootloader_main();
	}

	jump_to_flash(FLASH_FW_ADDR, 0);
}
