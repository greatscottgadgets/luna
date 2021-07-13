/*
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */


__attribute__((naked,section(".init"))) void _start(void)
{
	asm(
		/* Set up our global pointer. */
		".option push\n\t"
		".option norelax\n\t"
		"la gp, __global_pointer$\n\t"
		".option pop\n\t"

		/* Set up our primary interrut dispatcher. */
		"la t0, _interrupt_handler \n\t"
		"csrw mtvec, t0\n\t"

		/* Set up our stack. */
		"la sp, __stack_top\n\t"
		"add s0, sp, zero\n\t"

		/*
		 * NOTE: In most cases, we'd clear the BSS, here.
		 *
		 * In our case, our FPGA automaticaly starts with all of our RAM
		 * initialized to zero; so our BSS comes pre-cleared. We'll skip the
		 * formality of re-clearing it.
		 */

		/* Enable interrupts. */
		"li t0, 0x800\n\t"
		"csrs mie, t0\n\t"
	
		/* Finally, start our main routine. */
		"jal zero, main \n\t"
	);
}


__attribute__((naked,section(".init"))) void _interrupt_handler(void)
{
	asm(
		"addi sp, sp, -16 * 4\n\t"
		"sw ra,  0 * 4(sp)\n\t"
		"sw t0,  1 * 4(sp)\n\t"
		"sw t1,  2 * 4(sp)\n\t"
		"sw t2,  3 * 4(sp)\n\t"
		"sw a0,  4 * 4(sp)\n\t"
		"sw a1,  5 * 4(sp)\n\t"
		"sw a2,  6 * 4(sp)\n\t"
		"sw a3,  7 * 4(sp)\n\t"
		"sw a4,  8 * 4(sp)\n\t"
		"sw a5,  9 * 4(sp)\n\t"
		"sw a6, 10 * 4(sp)\n\t"
		"sw a7, 11 * 4(sp)\n\t"
		"sw t3, 12 * 4(sp)\n\t"
		"sw t4, 13 * 4(sp)\n\t"
		"sw t5, 14 * 4(sp)\n\t"
		"sw t6, 15 * 4(sp)\n\t"
		"call dispatch_isr\n\t"
		"lw ra,  0 * 4(sp)\n\t"
		"lw t0,  1 * 4(sp)\n\t"
		"lw t1,  2 * 4(sp)\n\t"
		"lw t2,  3 * 4(sp)\n\t"
		"lw a0,  4 * 4(sp)\n\t"
		"lw a1,  5 * 4(sp)\n\t"
		"lw a2,  6 * 4(sp)\n\t"
		"lw a3,  7 * 4(sp)\n\t"
		"lw a4,  8 * 4(sp)\n\t"
		"lw a5,  9 * 4(sp)\n\t"
		"lw a6, 10 * 4(sp)\n\t"
		"lw a7, 11 * 4(sp)\n\t"
		"lw t3, 12 * 4(sp)\n\t"
		"lw t4, 13 * 4(sp)\n\t"
		"lw t5, 14 * 4(sp)\n\t"
		"lw t6, 15 * 4(sp)\n\t"
		"addi sp, sp, 16*4\n\t"
		"mret\n\t"
	);
}


asm(
	".global __mulsi3\n\t"
	"__mulsi3:\n\t"
	"li	a2,0\n\t"
	"beqz	a0,24\n\t"
	"andi	a3,a0,1\n\t"
	"neg	a3,a3\n\t"
	"and	a3,a3,a1\n\t"
	"add	a2,a3,a2\n\t"
	"srli	a0,a0,0x1\n\t"
	"slli	a1,a1,0x1\n\t"
	"bnez	a0,8\n\t"
	"mv	a0,a2\n\t"
	"ret\n\t"
);
