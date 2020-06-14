/*
 * Copyright (c) 2019 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <stdint.h>
#include "common/hw.h"

#define NVM_DFLL_COARSE_POS    58
#define NVM_DFLL_COARSE_SIZE   6
#define NVM_DFLL_FINE_POS      64
#define NVM_DFLL_FINE_SIZE     10

uint32_t dfll_nvm_val() {
  uint32_t coarse = ( *((uint32_t *)(NVMCTRL_OTP4)
      + (NVM_DFLL_COARSE_POS / 32))
    >> (NVM_DFLL_COARSE_POS % 32))
    & ((1 << NVM_DFLL_COARSE_SIZE) - 1);
  if (coarse == 0x3f) {
    coarse = 0x1f;
  }
  uint32_t fine = ( *((uint32_t *)(NVMCTRL_OTP4)
      + (NVM_DFLL_FINE_POS / 32))
    >> (NVM_DFLL_FINE_POS % 32))
    & ((1 << NVM_DFLL_FINE_SIZE) - 1);
  if (fine == 0x3ff) {
    fine = 0x1ff;
  }

  return SYSCTRL_DFLLVAL_COARSE(coarse) | SYSCTRL_DFLLVAL_FINE(fine);
}

void dfll_wait_for_sync() {
  while (!SYSCTRL->PCLKSR.bit.DFLLRDY);
}

void gclk_enable(uint32_t id, uint32_t src, uint32_t div) {
  GCLK->GENDIV.reg = GCLK_GENDIV_ID(id) | GCLK_GENDIV_DIV(div);
  GCLK->GENCTRL.reg = GCLK_GENCTRL_ID(id) | GCLK_GENCTRL_GENEN | GCLK_GENCTRL_SRC(src);
}

void gclk_init() {
  // Various bits in the INTFLAG register can be set to one at startup.
  SYSCTRL->INTFLAG.reg = SYSCTRL_INTFLAG_BOD33RDY | SYSCTRL_INTFLAG_BOD33DET |
      SYSCTRL_INTFLAG_DFLLRDY;

  NVMCTRL->CTRLB.bit.RWS = 2;

  // Initialize GCLK
  PM->APBAMASK.reg |= PM_APBAMASK_GCLK;
  GCLK->CTRL.reg = GCLK_CTRL_SWRST;
  while (GCLK->CTRL.reg & GCLK_CTRL_SWRST);

  // SERCOM slow clock (Shared by all SERCOM)
  GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
      GCLK_CLKCTRL_GEN(0) |
      GCLK_CLKCTRL_ID(SERCOM0_GCLK_ID_SLOW);
}

// Configure DFLL in USB recovery mode
const uint32_t dfll_ctrl_usb
  = SYSCTRL_DFLLCTRL_ENABLE
  | SYSCTRL_DFLLCTRL_CCDIS
  | SYSCTRL_DFLLCTRL_BPLCKC
  | SYSCTRL_DFLLCTRL_USBCRM
  | SYSCTRL_DFLLCTRL_ONDEMAND;

void clock_init_usb(u8 clk_system) {
  gclk_init();

  // Disable ONDEMAND mode while writing configurations (errata 9905)
  SYSCTRL->DFLLCTRL.reg = dfll_ctrl_usb & ~SYSCTRL_DFLLCTRL_ONDEMAND;
  dfll_wait_for_sync();
  SYSCTRL->DFLLVAL.reg = dfll_nvm_val();
  dfll_wait_for_sync();
  SYSCTRL->DFLLCTRL.reg = dfll_ctrl_usb;

  gclk_enable(clk_system, GCLK_SOURCE_DFLL48M, 1);
  while (GCLK->STATUS.bit.SYNCBUSY);
}

void clock_init_crystal(u8 clk_system, u8 clk_32k) {
  gclk_init();

  SYSCTRL->XOSC32K.reg
    = SYSCTRL_XOSC32K_ENABLE
    | SYSCTRL_XOSC32K_XTALEN
    | SYSCTRL_XOSC32K_EN32K
    | SYSCTRL_XOSC32K_AAMPEN
    | SYSCTRL_XOSC32K_RUNSTDBY;

  gclk_enable(clk_32k, GCLK_SOURCE_XOSC32K, 1);

  GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
      GCLK_CLKCTRL_GEN(clk_32k) |
      GCLK_CLKCTRL_ID(SYSCTRL_GCLK_ID_DFLL48);

  SYSCTRL->DFLLCTRL.reg = SYSCTRL_DFLLCTRL_ENABLE;
  dfll_wait_for_sync();
  SYSCTRL->DFLLVAL.reg = dfll_nvm_val();
  dfll_wait_for_sync();
  SYSCTRL->DFLLMUL.reg
    = SYSCTRL_DFLLMUL_MUL(1465) // round(48000000 / 32768)
    | SYSCTRL_DFLLMUL_CSTEP((0x1f / 4))
    | SYSCTRL_DFLLMUL_FSTEP((0xff / 4));
  dfll_wait_for_sync();
  SYSCTRL->DFLLCTRL.reg = SYSCTRL_DFLLCTRL_ENABLE | SYSCTRL_DFLLCTRL_MODE;
  dfll_wait_for_sync();
  SYSCTRL->DFLLCTRL.reg = SYSCTRL_DFLLCTRL_ENABLE | SYSCTRL_DFLLCTRL_MODE | SYSCTRL_DFLLCTRL_ONDEMAND;

  gclk_enable(clk_system, GCLK_SOURCE_DFLL48M, 1);
  while (GCLK->STATUS.bit.SYNCBUSY);
}
