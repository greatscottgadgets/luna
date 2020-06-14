/*
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#define MIE_MEIE        0x800

.section .init, "ax"

.global _start
_start:
	/* Set up our global pointer. */
	.option push
	.option norelax
	la gp, __global_pointer$
	.option pop

	/* Set up our primary interrut dispatcher. */
	la t0, _interrupt_handler
	csrw mtvec, t0

	/* Set up our stack. */
	la sp, __stack_top
	add s0, sp, zero

	/*
	 * NOTE: In most cases, we'd clear the BSS, here.
	 *
	 * In our case, our FPGA automaticaly starts with all of our RAM
	 * initialized to zero; so our BSS comes pre-cleared. We'll skip the
	 * formality of re-clearing it.
	 */

	/* Enable interrupts. */
	li t0, MIE_MEIE
	csrs mie, t0

	/* Finally, start our main routine. */
	jal zero, main


/**
 * Re-entry point for interrupts.
 */
_interrupt_handler:
	addi sp, sp, -16 * 4
	sw ra,  0 * 4(sp)
	sw t0,  1 * 4(sp)
	sw t1,  2 * 4(sp)
	sw t2,  3 * 4(sp)
	sw a0,  4 * 4(sp)
	sw a1,  5 * 4(sp)
	sw a2,  6 * 4(sp)
	sw a3,  7 * 4(sp)
	sw a4,  8 * 4(sp)
	sw a5,  9 * 4(sp)
	sw a6, 10 * 4(sp)
	sw a7, 11 * 4(sp)
	sw t3, 12 * 4(sp)
	sw t4, 13 * 4(sp)
	sw t5, 14 * 4(sp)
	sw t6, 15 * 4(sp)
	call dispatch_isr
	lw ra,  0 * 4(sp)
	lw t0,  1 * 4(sp)
	lw t1,  2 * 4(sp)
	lw t2,  3 * 4(sp)
	lw a0,  4 * 4(sp)
	lw a1,  5 * 4(sp)
	lw a2,  6 * 4(sp)
	lw a3,  7 * 4(sp)
	lw a4,  8 * 4(sp)
	lw a5,  9 * 4(sp)
	lw a6, 10 * 4(sp)
	lw a7, 11 * 4(sp)
	lw t3, 12 * 4(sp)
	lw t4, 13 * 4(sp)
	lw t5, 14 * 4(sp)
	lw t6, 15 * 4(sp)
	addi sp, sp, 16*4
	mret
