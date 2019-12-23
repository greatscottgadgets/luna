#include "util.h"

#define NVM_MEMORY        ((volatile uint16_t *)FLASH_ADDR)

uint32_t nvm_flash_size() {
  return NVMCTRL->PARAM.bit.NVMP*FLASH_PAGE_SIZE;
}

void nvm_init() {
  NVMCTRL->CTRLB.bit.MANW = 1;
}

void nvm_address(uint32_t addr) {
  NVMCTRL->ADDR.reg = addr >> 1;
}

void nvm_wait() {
  while (!NVMCTRL->INTFLAG.bit.READY);
}

void nvm_command(uint32_t command) {
  NVMCTRL->CTRLA.reg = NVMCTRL_CTRLA_CMDEX_KEY | NVMCTRL_CTRLA_CMD(command);
  nvm_wait();
}

void nvm_erase_row(uint32_t addr) {
  nvm_address(addr);
  nvm_command(NVMCTRL_CTRLA_CMD_ER);
}

void nvm_write_page(uint32_t addr, uint8_t* buf, uint8_t len) {
  uint32_t nvm_addr = addr/2;

  // NVM must be accessed as a series of 16-bit words
  for (uint16_t i = 0; i < len; i += 2) {
    uint16_t data = buf[i];
    if (i < (len - 1)) data |= (buf[i + 1] << 8);

    NVM_MEMORY[nvm_addr++] = data;
  }

  /* Perform a manual NVM write when the length of data to be programmed is
   * less than page size */
  nvm_command(NVMCTRL_CTRLA_CMD_WP);
}

void nvm_invalidate_cache() {
  nvm_command(NVMCTRL_CTRLA_CMD_INVALL);
}
