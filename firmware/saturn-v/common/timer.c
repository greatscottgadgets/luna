/*
 * Copyright (c) 2019 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "common/hw.h"

void timer_clock_enable(TimerId id) {
    PM->APBCMASK.reg |= 1 << (PM_APBCMASK_TCC0_Pos + id);

    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
        GCLK_CLKCTRL_GEN(0) |
        GCLK_CLKCTRL_ID(TCC0_GCLK_ID + id/2);
}

// Starts timer countdown
void tcc_delay_start(TimerId id, u32 ticks) {
    tcc(id)->PER.reg = ticks;
    tcc(id)->CTRLBSET.reg = TCC_CTRLBSET_CMD_RETRIGGER;
}

// disables timer delay
void tcc_delay_disable(TimerId id) {
    tcc(id)->INTENCLR.reg = TC_INTENSET_OVF;
    tcc(id)->CTRLA.bit.ENABLE = 0;
}

// sets up a timer to count down in one-shot mode.
void tcc_delay_enable(TimerId id) {
    timer_clock_enable(id);

    tcc(id)->CTRLA.reg = TCC_CTRLA_PRESCALER_DIV256;
    tcc(id)->CTRLBSET.reg = TCC_CTRLBSET_DIR | TCC_CTRLBSET_ONESHOT;

    while (tcc(id)->SYNCBUSY.reg > 0);

    tcc(id)->CTRLA.bit.ENABLE = 1;
    tcc(id)->INTENSET.reg = TCC_INTENSET_OVF;
}
