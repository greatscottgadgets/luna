#include "common/hw.h"
#include <string.h>

DMA_DESC_ALIGN DmacDescriptor dma_descriptors[12];
DMA_DESC_ALIGN DmacDescriptor dma_descriptors_wb[12];

void dma_init() {
    memset(&dma_descriptors, 0, sizeof(dma_descriptors));
    memset(&dma_descriptors_wb, 0, sizeof(dma_descriptors_wb));

    PM->AHBMASK.reg |= PM_AHBMASK_DMAC;
    PM->APBBMASK.reg |= PM_APBBMASK_DMAC;

    DMAC->CTRL.bit.DMAENABLE = 0;
    DMAC->CTRL.bit.SWRST = 1;

    DMAC->BASEADDR.reg = (unsigned) &dma_descriptors;
    DMAC->WRBADDR.reg = (unsigned) &dma_descriptors_wb;

    DMAC->CTRL.reg = DMAC_CTRL_DMAENABLE | DMAC_CTRL_LVLEN(0xf);
}

void dma_abort(DmaChan chan) {
    DMAC->CHID.reg = chan;
    DMAC->CHCTRLA.reg = 0;
}

u32 dma_remaining(DmaChan chan) {
    return dma_descriptors_wb[chan].BTCNT.reg;
}

const u8 dummy_tx = 0x99;
void dma_fill_sercom_tx(DmacDescriptor* desc, SercomId id, u8 *src, unsigned size) {
    // doesn't matter if this is SPI.DATA or USART.DATA. both are in the same address
    desc->DSTADDR.reg = (unsigned) &sercom(id)->SPI.DATA;
    desc->BTCNT.reg = size;
    if (src != NULL) {
        desc->SRCADDR.reg = (unsigned) src + size;
        desc->BTCTRL.reg = DMAC_BTCTRL_VALID | DMAC_BTCTRL_SRCINC;
    } else {
        desc->SRCADDR.reg = (unsigned) &dummy_tx;
        desc->BTCTRL.reg = DMAC_BTCTRL_VALID;
    }
}


u8 dummy_rx = 0;
void dma_fill_sercom_rx(DmacDescriptor* desc, SercomId id, u8 *dst, unsigned size) {
    // doesn't matter if this is SPI.DATA or USART.DATA. both are in the same address
    desc->SRCADDR.reg = (unsigned) &sercom(id)->SPI.DATA;
    desc->BTCNT.reg = size;
    if (dst != NULL) {
        desc->DSTADDR.reg = (unsigned) dst + size;
        desc->BTCTRL.reg = DMAC_BTCTRL_VALID | DMAC_BTCTRL_DSTINC | DMAC_BTCTRL_EVOSEL_BEAT;
    } else {
        desc->DSTADDR.reg = (unsigned) &dummy_rx;
        desc->BTCTRL.reg = DMAC_BTCTRL_VALID;
    }
}

void dma_sercom_configure_tx(DmaChan chan, SercomId id) {
    DMAC->CHID.reg = chan;
    DMAC->CHCTRLA.reg = DMAC_CHCTRLA_SWRST;
    DMAC->CHCTRLB.reg = DMAC_CHCTRLB_TRIGACT_BEAT | DMAC_CHCTRLB_TRIGSRC(id*2 + 2);
}

void dma_sercom_configure_rx(DmaChan chan, SercomId id) {
    DMAC->CHID.reg = chan;
    DMAC->CHCTRLA.reg = DMAC_CHCTRLA_SWRST;
    DMAC->CHCTRLB.reg = DMAC_CHCTRLB_TRIGACT_BEAT | DMAC_CHCTRLB_TRIGSRC(id*2 + 1);
}

void dma_link_chain(DmacDescriptor* chain, u32 count) {
    for (u32 i = 0; i<count-1; i++) {
        chain[i].DESCADDR.reg = (unsigned) &chain[i+1];
    }
    chain[count-1].DESCADDR.reg = 0;
}

void dma_start_descriptor(DmaChan chan, DmacDescriptor* chain) {
    DMAC->CHID.reg = chan;
    DMAC->CHCTRLA.reg = 0;
    memcpy(&dma_descriptors[chan], &chain[0], sizeof(DmacDescriptor));
    DMAC->CHCTRLA.reg = DMAC_CHCTRLA_ENABLE;
}

void dma_sercom_start_tx(DmaChan chan, SercomId id, u8* src, unsigned size) {
    DMAC->CHID.reg = chan;
    DMAC->CHCTRLA.reg = 0;
    dma_fill_sercom_tx(&dma_descriptors[chan], id, src, size);
    dma_descriptors[chan].DESCADDR.reg = 0;
    DMAC->CHCTRLA.reg = DMAC_CHCTRLA_ENABLE;
}

void dma_sercom_start_rx(DmaChan chan, SercomId id, u8* dst, unsigned size) {
    DMAC->CHID.reg = chan;
    DMAC->CHCTRLA.reg = 0;
    dma_fill_sercom_rx(&dma_descriptors[chan], id, dst, size);
    dma_descriptors[chan].DESCADDR.reg = 0;
    DMAC->CHCTRLA.reg = DMAC_CHCTRLA_ENABLE;
}
