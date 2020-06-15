/*
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */
.section .init, "ax"

.global _start
_start:
    .cfi_startproc
    .cfi_undefined ra

    /* Set up our global pointer. */
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop

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

    /* Finally, start our main routine. */
    jal zero, main

    .cfi_endproc
    .end
