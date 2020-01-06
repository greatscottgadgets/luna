/*
 * Code for dispatching Apollo vendor requests.
 * This file is part of LUNA.
 *
 * Currently, we support only a vendor-request based protocol, as we're trying to
 * keep code size small for a potential switch to a SAMD11. This likely means we
 * want to avoid the overhead of the libgreat comms API.
 */



#include <sam.h>
#include <tusb.h>

#include "spi.h"
#include "led.h"
#include "jtag.h"
#include "selftest.h"
#include "debug_spi.h"


// Supported vendor requests.
enum {
	VENDOR_REQUEST_GET_ID          = 0xa0,
	VENDOR_REQUEST_SET_LED_PATTERN = 0xa1,

	//
	// JTAG requests.
	//
	VENDOR_REQUEST_JTAG_START              = 0xbf,
	VENDOR_REQUEST_JTAG_STOP               = 0xbe,

	VENDOR_REQUEST_JTAG_CLEAR_OUT_BUFFER   = 0xb0,
	VENDOR_REQUEST_JTAG_SET_OUT_BUFFER     = 0xb1,
	VENDOR_REQUEST_JTAG_GET_IN_BUFFER      = 0xb2,
	VENDOR_REQUEST_JTAG_SCAN               = 0xb3,
	VENDOR_REQUEST_JTAG_RUN_CLOCK          = 0xb4,
	VENDOR_REQUEST_JTAG_GOTO_STATE         = 0xb5,
	VENDOR_REQUEST_JTAG_GET_STATE          = 0xb6,
	VENDOR_REQUEST_JTAG_BULK_SCAN          = 0xb7,


	//
	// Debug SPI requests
	//
	VENDOR_REQUEST_DEBUG_SPI_SEND          = 0x50,
	VENDOR_REQUEST_DEBUG_SPI_READ_RESPONSE = 0x51,


	//
	// Self-test requests.
	//
	VENDOR_REQUEST_GET_RAIL_VOLTAGE      = 0xe0
};


/**
 * Simple request that's used to identify the running firmware; mostly a sanity check.
 */
bool handle_get_id_request(uint8_t rhport, tusb_control_request_t const* request)
{
	static char description[] = "Apollo Debug Module";
	return tud_control_xfer(rhport, request, description, sizeof(description));
}


/**
 * Request that changes the active LED pattern.
 */
bool handle_set_led_pattern(uint8_t rhport, tusb_control_request_t const* request)
{
	led_set_blink_pattern(request->wValue);
	return tud_control_xfer(rhport, request, NULL, 0);
}



/**
 * Primary vendor request handler.
 */
bool tud_vendor_control_request_cb(uint8_t rhport, tusb_control_request_t const* request)
{
	// FIXME: clean this up to use a function pointer to grab the request?

	switch(request->bRequest) {
		case VENDOR_REQUEST_GET_ID:
			return handle_get_id_request(rhport, request);

		// JTAG requests
		case VENDOR_REQUEST_JTAG_CLEAR_OUT_BUFFER:
			return handle_jtag_request_clear_out_buffer(rhport, request);
		case VENDOR_REQUEST_JTAG_SET_OUT_BUFFER:
			return handle_jtag_request_set_out_buffer(rhport, request);
		case VENDOR_REQUEST_JTAG_GET_IN_BUFFER:
			return handle_jtag_request_get_in_buffer(rhport, request);
		case VENDOR_REQUEST_JTAG_SCAN:
			return handle_jtag_request_scan(rhport, request);
		case VENDOR_REQUEST_JTAG_RUN_CLOCK:
			return handle_jtag_run_clock(rhport, request);
		case VENDOR_REQUEST_JTAG_START:
			return handle_jtag_start(rhport, request);
		case VENDOR_REQUEST_JTAG_GOTO_STATE:
			return handle_jtag_go_to_state(rhport, request);
		case VENDOR_REQUEST_JTAG_STOP:
			return handle_jtag_stop(rhport, request);
		case VENDOR_REQUEST_JTAG_GET_STATE:
			return handle_jtag_get_state(rhport, request);

		// LED control requests.
		case VENDOR_REQUEST_SET_LED_PATTERN:
			return handle_set_led_pattern(rhport, request);

		// Debug SPI requests.
		case VENDOR_REQUEST_DEBUG_SPI_SEND:
			return handle_debug_spi_send(rhport, request);
		case VENDOR_REQUEST_DEBUG_SPI_READ_RESPONSE:
			return handle_debug_spi_get_response(rhport, request);

		// Self-test requests.
		case VENDOR_REQUEST_GET_RAIL_VOLTAGE:
			return handle_get_rail_voltage(rhport, request);

		default:
			return false;
	}

}

/**
 * Called when a vendor request is completed.
 *
 * This is used to complete any actions that need to happen once data is available, e.g.
 * during an IN transfer.
 */
bool tud_vendor_control_complete_cb(uint8_t rhport, tusb_control_request_t const * request)
{
	switch (request->bRequest) {
		case VENDOR_REQUEST_DEBUG_SPI_SEND:
			return handle_debug_spi_send_complete(rhport, request);
		default:
			return true;
	}

}
