/*
 * Copyright (c) 2019 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "common/hw.h"

void sercom_clock_enable(SercomId id, uint32_t clock_channel, u8 divider) {
    // prevent this clock write from changing any other clocks
    PM->APBCMASK.reg |= 1 << (PM_APBCMASK_SERCOM0_Pos + id);

    if (clock_channel != 0) {
      // clock generators 3-8 have 8 division factor bits - DIV[7:0]
      gclk_enable(clock_channel, GCLK_SOURCE_DFLL48M, divider);
    }

    // attach clock
    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
        GCLK_CLKCTRL_GEN(clock_channel) |
        GCLK_CLKCTRL_ID(SERCOM0_GCLK_ID_CORE + id);
}

inline void sercom_reset(SercomId id) {
    sercom(id)->SPI.CTRLA.reg = SERCOM_SPI_CTRLA_SWRST;
    while(sercom(id)->SPI.CTRLA.reg & SERCOM_SPI_CTRLA_SWRST);
}

void sercom_spi_slave_init(SercomId id, u32 dipo, u32 dopo, bool cpol, bool cpha) {
    sercom_reset(id);
    sercom(id)->SPI.CTRLA.reg = SERCOM_SPI_CTRLA_MODE_SPI_SLAVE;

    sercom(id)->SPI.CTRLB.reg
      = SERCOM_SPI_CTRLB_RXEN
      | SERCOM_SPI_CTRLB_SSDE
      | SERCOM_SPI_CTRLB_PLOADEN;

    sercom(id)->SPI.CTRLA.reg
      = SERCOM_SPI_CTRLA_ENABLE
      | SERCOM_SPI_CTRLA_MODE_SPI_SLAVE
      | SERCOM_SPI_CTRLA_DIPO(dipo)
      | SERCOM_SPI_CTRLA_DOPO(dopo)
      | (cpol ? SERCOM_SPI_CTRLA_CPOL : 0)
      | (cpha ? SERCOM_SPI_CTRLA_CPHA : 0);
}

void sercom_spi_master_init(SercomId id, u32 dipo, u32 dopo, bool cpol, bool cpha, u8 baud) {
    sercom_reset(id);
    sercom(id)->SPI.CTRLA.reg = SERCOM_SPI_CTRLA_MODE_SPI_MASTER;

    sercom(id)->SPI.CTRLB.reg
      = SERCOM_SPI_CTRLB_RXEN
      | SERCOM_SPI_CTRLB_SSDE;

    sercom(id)->SPI.BAUD.reg = baud;

    sercom(id)->SPI.CTRLA.reg
      = SERCOM_SPI_CTRLA_ENABLE
      | SERCOM_SPI_CTRLA_MODE_SPI_MASTER
      | SERCOM_SPI_CTRLA_DIPO(dipo)
      | SERCOM_SPI_CTRLA_DOPO(dopo)
      | (cpol ? SERCOM_SPI_CTRLA_CPOL : 0)
      | (cpha ? SERCOM_SPI_CTRLA_CPHA : 0);

}

void sercom_i2c_master_init(SercomId id, u8 baud) {
    sercom_reset(id);
    sercom(id)->I2CM.CTRLA.reg = SERCOM_I2CM_CTRLA_MODE_I2C_MASTER;
    sercom(id)->I2CM.BAUD.reg = baud;
    sercom(id)->I2CM.CTRLA.reg
        = SERCOM_I2CM_CTRLA_ENABLE
        | SERCOM_I2CM_CTRLA_MODE_I2C_MASTER;
    sercom(id)->I2CM.STATUS.reg = SERCOM_I2CM_STATUS_BUSSTATE(1);
}

void sercom_uart_init(SercomId id, u32 rxpo, u32 txpo, u32 baud) {
    sercom_reset(id);
    sercom(id)->USART.CTRLA.reg = SERCOM_USART_CTRLA_MODE_USART_INT_CLK;
    sercom(id)->USART.BAUD.reg = baud;
    sercom(id)->USART.CTRLB.reg
        = SERCOM_USART_CTRLB_RXEN
        | SERCOM_USART_CTRLB_TXEN;
    sercom(id)->USART.CTRLA.reg
        = SERCOM_USART_CTRLA_ENABLE
        | SERCOM_USART_CTRLA_MODE_USART_INT_CLK
        | SERCOM_SPI_CTRLA_DORD
        | SERCOM_USART_CTRLA_TXPO(txpo)
        | SERCOM_USART_CTRLA_RXPO(rxpo);
}
