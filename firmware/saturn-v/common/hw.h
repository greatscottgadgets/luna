/*
 * Copyright (c) 2019 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#pragma once
#include <parts.h>
#include <io.h>
#include "common/util.h"

const extern char *git_version;

inline static void pin_mux(Pin p) {
  if (p.pin & 1) {
    PORT->Group[p.group].PMUX[p.pin/2].bit.PMUXO = p.mux;
  } else {
    PORT->Group[p.group].PMUX[p.pin/2].bit.PMUXE = p.mux;
  }

  PORT->Group[p.group].PINCFG[p.pin].bit.PMUXEN = 1;
}

// all adc functions are on peripherial B (0x01)
inline static void pin_analog(Pin p) {
  if (p.pin & 1) {
    PORT->Group[p.group].PMUX[p.pin/2].bit.PMUXO = 0x1;
  } else {
    PORT->Group[p.group].PMUX[p.pin/2].bit.PMUXE = 0x1;
  }

  PORT->Group[p.group].PINCFG[p.pin].bit.PMUXEN = 1;
}

inline static void pin_gpio(Pin p) {
  PORT->Group[p.group].PINCFG[p.pin].bit.PMUXEN = 0;
}

inline static void pin_out(Pin p) {
  pin_gpio(p);
  PORT->Group[p.group].DIRSET.reg = (1<<p.pin);
}

inline static void pin_dir(Pin p, bool out) {
  if (out) {
    PORT->Group[p.group].DIRSET.reg = (1<<p.pin);
  } else {
    PORT->Group[p.group].DIRCLR.reg = (1<<p.pin);
  }
}

inline static void pin_high(Pin p) {
  PORT->Group[p.group].OUTSET.reg = (1<<p.pin);
}

inline static void pin_low(Pin p) {
  PORT->Group[p.group].OUTCLR.reg = (1<<p.pin);
}

inline static void pin_toggle(Pin p) {
  PORT->Group[p.group].OUTTGL.reg = (1<<p.pin);
}

inline static void pin_set(Pin p, bool high) {
  if (high) {
    PORT->Group[p.group].OUTSET.reg = (1<<p.pin);
  } else {
    PORT->Group[p.group].OUTCLR.reg = (1<<p.pin);
  }
}

inline static void pin_in(Pin p) {
  pin_gpio(p);
  PORT->Group[p.group].PINCFG[p.pin].bit.INEN = 1;
  PORT->Group[p.group].DIRCLR.reg = (1<<p.pin);
}

inline static void pin_pull_up(Pin p) {
  pin_in(p);
  PORT->Group[p.group].PINCFG[p.pin].bit.PULLEN = 1;
  pin_high(p);
}

inline static void pin_pull_down(Pin p) {
  pin_in(p);
  PORT->Group[p.group].PINCFG[p.pin].bit.PULLEN = 1;
  pin_low(p);
}

inline static void pin_float(Pin p) {
  pin_in(p);
  PORT->Group[p.group].PINCFG[p.pin].bit.PULLEN = 0;
}

inline static bool pin_read(Pin p) {
  return (PORT->Group[p.group].IN.reg & (1<<p.pin)) != 0;
}

inline static void pin_mux_eic(Pin p) {
    if (p.pin & 1) {
      PORT->Group[p.group].PMUX[p.pin/2].bit.PMUXO = 0;
    } else {
      PORT->Group[p.group].PMUX[p.pin/2].bit.PMUXE = 0;
    }

    PORT->Group[p.group].PINCFG[p.pin].bit.PMUXEN = 1;
}

inline static void eic_init() {
    PM->APBAMASK.reg |= PM_APBAMASK_EIC;

    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
        GCLK_CLKCTRL_GEN(0) |
        GCLK_CLKCTRL_ID(EIC_GCLK_ID);

    EIC->CTRL.reg = EIC_CTRL_ENABLE;
}

inline static u8 pin_extint(Pin p) {
  return p.pin % 16;
}

#define   EIC_CONFIG_SENSE_NONE      0x0u   /**< \brief (EIC_CONFIG) No detection */
#define   EIC_CONFIG_SENSE_RISE      0x1u   /**< \brief (EIC_CONFIG) Rising edge detection */
#define   EIC_CONFIG_SENSE_FALL      0x2u   /**< \brief (EIC_CONFIG) Falling edge detection */
#define   EIC_CONFIG_SENSE_BOTH      0x3u   /**< \brief (EIC_CONFIG) Both edges detection */
#define   EIC_CONFIG_SENSE_LEVEL     0x4u   /**< \brief (EIC_CONFIG) High level detection */
#define   EIC_CONFIG_SENSE_HIGH      0x4u   /**< \brief (EIC_CONFIG) High level detection */
#define   EIC_CONFIG_SENSE_LOW       0x5u   /**< \brief (EIC_CONFIG) Low level detection */

inline static void eic_config(Pin p, u8 config) {
  u8 i = pin_extint(p);
  u8 pos = (i % 8) * 4;
  EIC->CONFIG[i/8].reg = (EIC->CONFIG[i/8].reg & ~(0xf << pos)) | (config << pos);
}

inline static u8 eic_read_config(Pin p) {
  u8 i = pin_extint(p);
  u8 pos = (i % 8) * 4;
  return (EIC->CONFIG[i/8].reg >> pos) & 0xf;
}

inline static void evsys_init() {
    PM->APBCMASK.reg |= PM_APBCMASK_EVSYS;
}

#define EVSYS_USER_NONE -1

inline static void evsys_config(u8 channel, u8 source, u8 user) {
    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
        GCLK_CLKCTRL_GEN(0) |
        GCLK_CLKCTRL_ID(EVSYS_GCLK_ID_0 + channel);

    EVSYS->CHANNEL.reg = EVSYS_CHANNEL_CHANNEL(channel)
                       | EVSYS_CHANNEL_EVGEN(source)
                       | EVSYS_CHANNEL_PATH_SYNCHRONOUS | EVSYS_CHANNEL_EDGSEL_RISING_EDGE;

    if (user != EVSYS_USER_NONE) {
      EVSYS->USER.reg = EVSYS_USER_CHANNEL(channel + 1) | EVSYS_USER_USER(user);
    }
}

#define EVSYS_EVD(N) ((N)<=7 ? (1<<((N) + 8)) : (1 << (24 + (N) - 8)))

// analog.c
void adc_init(u8 channel, u8 refctrl);
u16 adc_sample();
u16 adc_read(Pin p, u32 gain);
void dac_init(u8 channel);
void dac_write(Pin p, u16 val);


// clock.c
void gclk_enable(uint32_t id, uint32_t src, uint32_t div);
void clock_init_usb(u8 clk_system);
void clock_init_crystal(u8 clk_system, u8 clk_32k);

// dma.c
#define DMA_DESC_ALIGN __attribute__((aligned(16)))

void dma_init();
void dma_sercom_start_tx(DmaChan chan, SercomId id, u8* src, unsigned size);
void dma_sercom_start_rx(DmaChan chan, SercomId id, u8* dst, unsigned size);
void dma_abort(DmaChan chan);
void dma_fill_sercom_tx(DmacDescriptor* desc, SercomId id, u8 *src, unsigned size);
void dma_fill_sercom_rx(DmacDescriptor* desc, SercomId id, u8 *dst, unsigned size);
void dma_sercom_configure_tx(DmaChan chan, SercomId id);
void dma_sercom_configure_rx(DmaChan chan, SercomId id);
void dma_link_chain(DmacDescriptor* chain, u32 count);
void dma_start_descriptor(DmaChan chan, DmacDescriptor* chain);
u32 dma_remaining(DmaChan chan);


// sercom.c

inline static Sercom* sercom(SercomId id) {
  return (Sercom*) (0x42000800U + id * 1024);
}

#define SERCOM_SPI_BAUD_8MHZ 2
#define SERCOM_SPI_BAUD_12MHZ 1
#define SERCOM_SPI_BAUD_24MHZ 0
void sercom_clock_enable(SercomId id, uint32_t clock_channel, u8 div);
void sercom_reset(SercomId id);
void sercom_spi_slave_init(SercomId id, u32 dipo, u32 dopo, bool cpol, bool cpha);
void sercom_spi_master_init(SercomId id, u32 dipo, u32 dopo, bool cpol, bool cpha, u8 baud);
void sercom_i2c_master_init(SercomId id, u8 baud);
void sercom_uart_init(SercomId id, u32 rxpo, u32 txpo, u32 baud);

inline static void jump_to_flash(uint32_t addr_p, uint32_t r0_val) {
  uint32_t *addr = (void*) addr_p;
  //__disable_irq();

  // Disable SysTick
  //SysTick->CTRL = 0;

  // TODO: reset peripherals

  // Switch to the the interrupt vector table in flash
  SCB->VTOR = (uint32_t) addr;

  // Set up the stack and jump to the reset vector
  uint32_t sp = addr[0];
  uint32_t pc = addr[1];
  register uint32_t r0 __asm__ ("r0") = r0_val;
  __asm__ volatile("mov sp, %0; bx %1" :: "r" (sp), "r" (pc), "r" (r0));
  (void) r0_val;
}

// timer

inline static Tc* tc(TimerId id) {
  return (Tc*) (0x42002C00U + (id - 3) * 1024);
}

inline static Tcc* tcc(TimerId id) {
  return (Tcc*) (0x42002000U + (id) * 1024);
}

void timer_clock_enable(TimerId id);

void tcc_delay_start(TimerId id, u32 ticks);
void tcc_delay_disable(TimerId id);
void tcc_delay_enable(TimerId id);

// wdt

inline static void wdt_reset(u32 clock_channel) {
  GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
      GCLK_CLKCTRL_GEN(clock_channel) |
      GCLK_CLKCTRL_ID(WDT_GCLK_ID);
  WDT->CONFIG.reg = 0x7; // 31ms
  WDT->CTRL.reg = WDT_CTRL_ENABLE;
}
