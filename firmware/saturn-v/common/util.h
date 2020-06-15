/*
 * Copyright (c) 2019 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;

typedef uint8_t DmaChan;
typedef uint8_t SercomId;
typedef uint8_t TimerId;
typedef struct Pin {
  u8 mux;
  u8 group;
  u8 pin;
  u8 chan;
} Pin;

#define SERCOM_HANDLER_(ID) SERCOM ## ID ## _Handler()
#define SERCOM_HANDLER(ID) SERCOM_HANDLER_(ID)

#define TC_HANDLER_(ID) TC ## ID ## _Handler()
#define TC_HANDLER(ID) TC_HANDLER_(ID)

#define TCC_HANDLER_(ID) TCC ## ID ## _Handler()
#define TCC_HANDLER(ID) TCC_HANDLER_(ID)

inline static void invalid() {
    __asm__("bkpt");
}
