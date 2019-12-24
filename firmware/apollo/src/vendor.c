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

#include "jtag.h"

// Supported vendor requests.
enum {
	VENDOR_REQUEST_GET_ID = 0xa0,

	// JTAG requests.
	VENDOR_REQUEST_JTAG_CLEAR_OUT_BUFFER = 0xb0,
	VENDOR_REQUEST_JTAG_SET_OUT_BUFFER   = 0xb1,
	VENDOR_REQUEST_JTAG_GET_IN_BUFFER    = 0xb2,
	VENDOR_REQUEST_JTAG_SCAN             = 0xb3,
	VENDOR_REQUEST_JTAG_RUN_CLOCK        = 0xb4
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

		default:
			return false;
	}

}
