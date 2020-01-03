/*
 * Self-test & factory validation functionality for LUNA.
 * This file is part of LUNA.
 */
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include <tusb.h>
#include <sam.h>
#include <hal/include/hal_gpio.h>
#include <hal/include/hal_adc_sync.h>

#include <hpl/gclk/hpl_gclk_base.h>
#include <hpl_pm_config.h>
#include <hpl/pm/hpl_pm_base.h>

struct adc_sync_descriptor adc;


enum {
	ADC_CHANNEL_2V5 = 0,
	ADC_CHANNEL_1V1 = 1
};

static void set_up_voltage_monitors(void)
{
	// Set up monitors for each of our primary voltage rails.
	_pm_enable_bus_clock(PM_BUS_APBC, ADC);
	_gclk_enable_channel(ADC_GCLK_ID, CONF_GCLK_ADC_SRC);

	adc_sync_init(&adc, ADC, NULL);
	adc_sync_set_reference(&adc,  ADC_REFCTRL_REFSEL_INT1V);
	adc_sync_set_resolution(&adc, ADC_CTRLB_RESSEL_12BIT_Val);

	// - We don't sample the 5V rail, as it's above what we're capable
	//   of sampling; and we don't sample the 3V3, as we're powered by it.
	//   This makes sense; as if either of these were missing, we wouldn't be
	//   up and communicating. :)

	// Channel 0 monitors the 2V5 rail.
	adc_sync_enable_channel(&adc, ADC_CHANNEL_2V5);
	adc_sync_set_inputs(&adc, ADC_INPUTCTRL_MUXPOS_PIN0_Val, ADC_INPUTCTRL_MUXNEG_GND_Val, ADC_CHANNEL_2V5);
	gpio_set_pin_function(PIN_PA02, PINMUX_PA02B_ADC_AIN0);

	// Channel 1 monitors the 1V1 rail.
	adc_sync_enable_channel(&adc, ADC_CHANNEL_1V1);
	adc_sync_set_inputs(&adc, ADC_INPUTCTRL_MUXPOS_PIN3_Val, ADC_INPUTCTRL_MUXNEG_GND_Val, ADC_CHANNEL_1V1);
	gpio_set_pin_function(PIN_PB09, PINMUX_PB09B_ADC_AIN3);
}

/**
 * Initialize our self-test functionality.
 */
void selftest_init(void)
{
	set_up_voltage_monitors();
}


/**
 * Vendor request that reads the voltage on one of the supply rails.
 */
bool handle_get_rail_voltage(uint8_t rhport, tusb_control_request_t const* request)
{
	static uint16_t reading;
	
	// TODO: make this an arbitrary rail.
	while(!adc_sync_read_channel(&adc, ADC_CHANNEL_1V1, (void *)&reading, sizeof(reading)));
	return tud_control_xfer(rhport, request, &reading, sizeof(reading));
}
