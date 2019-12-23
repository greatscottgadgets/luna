#include "hw.h"

void adc_init(u8 channel, u8 refctrl) {
    // set up clock
    PM->APBCMASK.reg |= PM_APBCMASK_ADC;

    // divide prescaler by 512 (93.75KHz), max adc freq is 2.1MHz
    ADC->CTRLB.reg = ADC_CTRLB_PRESCALER_DIV512;

    // enable clock adc channel
    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
        GCLK_CLKCTRL_GEN(channel) |
        GCLK_CLKCTRL_ID(ADC_GCLK_ID);

    ADC->CALIB.reg =
        ADC_CALIB_BIAS_CAL(
            (*(uint32_t *)ADC_FUSES_BIASCAL_ADDR >> ADC_FUSES_BIASCAL_Pos)
        ) |
        ADC_CALIB_LINEARITY_CAL(
            (*(uint64_t *)ADC_FUSES_LINEARITY_0_ADDR >> ADC_FUSES_LINEARITY_0_Pos)
        );

    ADC->REFCTRL.reg = refctrl;

    ADC->CTRLA.reg = ADC_CTRLA_ENABLE; // enable
    while(ADC->STATUS.reg & ADC_STATUS_SYNCBUSY);
}

u16 adc_sample() {
    ADC->SWTRIG.reg = ADC_SWTRIG_START;
    while(!(ADC->INTFLAG.reg & ADC_INTFLAG_RESRDY)); // wait until result is ready
    return ADC->RESULT.reg;
}

u16 adc_read(Pin p, u32 gain) {
    // switch pin mux to analog in
    pin_analog(p);

    ADC->INPUTCTRL.reg = (ADC_INPUTCTRL_MUXPOS(p.chan) // select from proper pin
        | ADC_INPUTCTRL_MUXNEG_GND // 0 = gnd
        | gain);

    return adc_sample();
}

void dac_init(u8 channel) {
    // hook up clk
    PM->APBCMASK.reg |= PM_APBCMASK_DAC;
    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN |
    GCLK_CLKCTRL_GEN(channel) |
    GCLK_CLKCTRL_ID(DAC_GCLK_ID);
}

void dac_write(Pin p, u16 val) {
    // switch dac pinmux. this must be PA02
    pin_analog(p);

    // disable
    DAC->CTRLA.reg &= ~DAC_CTRLA_ENABLE;

    // set vcc as reference voltage
    DAC->CTRLB.reg = DAC_CTRLB_EOEN |DAC_CTRLB_REFSEL_AVCC;

    // enable
    DAC->CTRLA.reg = DAC_CTRLA_ENABLE;

    DAC->DATA.reg = val;
}
