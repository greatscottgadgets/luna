/**
 * This file is part of LUNA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * Minimal example for the LUNA `eptri`-equivalent interface.
 *
 * Note that this example is minimal, and meant to offer an example of how to use the
 * LUNA `eptri` interface; and not a complete and correct `eptri` based USB stack.
 */


#include <stdbool.h>
#include "resources.h"

#define ARRAY_SIZE(array) (sizeof(array) / sizeof(*array))


/**
 * Control request constants.
 */
enum {

	// Request flags.
	DIRECTION_IN_MASK         = 0x80,

	REQUEST_TYPE_STANDARD     = 0x00,

	// Request types.
	REQUEST_SET_ADDRESS       = 0x05,
	REQUEST_GET_DESCRIPTOR    = 0x06,
	REQUEST_SET_CONFIGURATION = 0x09,

	// Descriptor types
	DESCRIPTOR_DEVICE         = 0x01,
	DESCRIPTOR_CONFIGURATION  = 0x02,
	DESCRIPTOR_STRING         = 0x03
};


/**
 * Struct representing a USB setup request.
 */
union usb_setup_request
{
	struct
	{
		union {
			struct
			{
				uint8_t bmRequestType;
				uint8_t bRequest;
			};

			uint16_t wRequestAndType;
		};

    uint16_t wValue;
    uint16_t wIndex;
    uint16_t wLength;
    };

	// Window that allows us to capture raw data into the setup request, easily.
	uint8_t raw_data[8];
};
typedef union usb_setup_request usb_setup_request_t;


//
// Globals
//
usb_setup_request_t last_setup_packet;


//
// Descriptors.
//

static const uint8_t usb_device_descriptor[] = {
    0x12, 0x01, 0x00, 0x02, 0x00, 0x00, 0x00, 0x40,
    0xd0, 0x16, 0x3b, 0x0f, 0x01, 0x01, 0x01, 0x02,
    0x00, 0x01
};


static const uint8_t usb_config_descriptor[] = {
    0x09, 0x02, 0x12, 0x00, 0x01, 0x01, 0x01, 0x80,
    0x32, 0x09, 0x04, 0x00, 0x00, 0x00, 0xfe, 0x00,
    0x00, 0x02
};

static const uint8_t usb_string0_descriptor[] = {
    0x04, 0x03, 0x09, 0x04,
};

static const uint8_t usb_string1_descriptor[] = {
    0x0a, 0x03, 'L', 0x00, 'U', 0x00, 'N', 0x00, 'A', 0x00
};

static const uint8_t usb_string2_descriptor[] = {
	0x22, 0x03,
	'T', 0, 'r', 0, 'i', 0, '-', 0, 'F', 0, 'I', 0, 'F', 0, 'O', 0,
	' ', 0, 'E', 0, 'x', 0, 'a', 0, 'm', 0, 'p', 0, 'l', 0, 'e', 0
};


//
// Support functions.
//


/**
 * Transmits a single charater over our example UART.
 */
void print_char(char c)
{
	while(!uart_tx_rdy_read());
	uart_tx_data_write(c);
}


/**
 * Transmits a string over our UART.
 */
void uart_puts(char *str)
{
	for (char *c = str; *c; ++c) {
		if (*c == '\n') {
			print_char('\r');
		}

		print_char(*c);
	}
}


/**
 * Prints a hex character over our UART.
 */
void print_nibble(uint8_t nibble)
{
	static const char hexits[] = "0123456789abcdef";
	print_char(hexits[nibble & 0xf]);
}


/**
 * Prints a single byte, in hex, over our UART.
 */
void print_byte(uint8_t byte)
{
	print_nibble(byte >> 4);
	print_nibble(byte & 0xf);
}


/**
 * Reads a setup request from our interface, populating our SETUP request field.
 */
void read_setup_request(void)
{
	for (uint8_t i = 0; i < 8; ++i) {

		// Block until we have setup data to read.
		while(!setup_have_read());

		// Once it's available, read the setup field for our packet.
		uint8_t byte = setup_data_read();
		last_setup_packet.raw_data[i] = byte;
	}
}

/**
 * Transmits a single data packet on an IN endpoint.
 *
 * @param endpoint The endpoint -number- on which we should respond.
 * @param data     The data packet to respond with.
 * @param length   The total length of the data to send.
 */
 void send_packet(uint8_t endpoint, const void *data, uint16_t length)
 {
	const uint8_t *buffer = data;

	// Clear our output FIFO, ensuring we start fresh.
	in_ep_reset_write(1);

	// Send data until we run out of bytes.
	while (length) {
		in_ep_data_write(*buffer);

		++buffer;
		--length;
	}

	// And prime our IN endpoint.
	in_ep_epno_write(endpoint);

 }


/**
 * Transmits a single data packet in response to an control request.
 *
 * @param data            The data packet to respond with.
 * @param data_length     The length of the data object that can be sent. If this is longer
 *                        than the last request length, the response will automatically be
 *                        truncated to the requested length.
 *
 */
 void send_control_response(const void *data, uint16_t data_length)
 {
	 uint16_t length = data_length;

	// If the host is requesting less than the maximum amount of data,
	// only respond with the amount of data requested.
	if (last_setup_packet.wLength < data_length) {
		length = last_setup_packet.wLength;
	}

	 send_packet(0, data, length);
 }


/**
 * Clears the contents of the Receive buffer.
 */
void flush_receive_buffer(void)
{
	out_ep_reset_write(1);
}


/**
 * Prepares an endpoint to receive a single OUT packet.
 */
void prime_receive(uint8_t endpoint)
{
	flush_receive_buffer();

	// Select our endpoint, and enable it to prime a read.
	out_ep_epno_write(endpoint);
	out_ep_enable_write(1);
}


/**
 * Handles acknowledging the status stage of an incoming control request.
 */
void ack_status_stage()
{

	// If this is an IN request, read a zero-length packet (ZLP) from the host..
	if (last_setup_packet.bmRequestType & DIRECTION_IN_MASK) {
		prime_receive(0);
	}
	// ... otherwise, send a ZLP.
	else {
		send_packet(0, 0, 0);
	}
}


/**
 * Stalls the current control request
 * For this example, we'll assume we're always targeting EP0.
 */
void stall_request(void)
{
	in_ep_stall_write(1);
	out_ep_stall_write(1);
}

//
// Request handlers.
//

/**
 * Handle SET_ADDRESS requests.
 */
void handle_set_address(void)
{
	ack_status_stage();

	// FIXME: we should wait to get our final ACK on the status stage before applying this address

	// Apply our address.
	setup_address_write(last_setup_packet.wValue);
}


/**
 * Handle SET_CONFIGURATIOn requests.
 */
void handle_set_configuration(uint8_t configuration)
{
	// We only have a single configuration; so only accept configuration number '1',
	// or configuration '0' (unconfigured).
	if (configuration > 1) {
		stall_request();
		return;
	}

	// TODO: apply our configuration to the device state
	ack_status_stage();
}



/**
 * Sends a string descriptor, by number.
 */
void handle_string_descriptor(uint8_t number)
{
	switch (number) {

		case 0:
			send_control_response(usb_string0_descriptor, ARRAY_SIZE(usb_string0_descriptor));
			break;

		case 1:
			send_control_response(usb_string1_descriptor, ARRAY_SIZE(usb_string1_descriptor));
			break;

		case 2:
			send_control_response(usb_string2_descriptor, ARRAY_SIZE(usb_string2_descriptor));
			break;

		default:
			stall_request();
			return;
	}

	ack_status_stage();
}


/**
 * Handle GET_DESCRIPTOR requests.
 */
void handle_get_descriptor(void)
{
	uint8_t descriptor_type   = last_setup_packet.wValue >> 8;
	uint8_t descriptor_number = last_setup_packet.wValue & 0xFF;

	switch (descriptor_type) {

		case DESCRIPTOR_DEVICE:
			send_control_response(usb_device_descriptor, ARRAY_SIZE(usb_device_descriptor));
			break;

		case DESCRIPTOR_CONFIGURATION:
			if (descriptor_number != 0) {
				stall_request();
				return;
			}

			send_control_response(usb_config_descriptor, ARRAY_SIZE(usb_config_descriptor));
			break;

		case DESCRIPTOR_STRING:
			handle_string_descriptor(descriptor_number);
			return;

		default:
			stall_request();
			return;

	}

	ack_status_stage();
}


/**
 * Unhandled request handler.
 */
void unhandled_request(void)
{
	stall_request();
}


void handle_setup_request(void)
{
	// Extract our type (e.g. standard/class/vendor) from our SETUP request.
	uint8_t type = (last_setup_packet.bmRequestType >> 5) & 0b11;

	// TODO: Get rid of this once we move to be fully compatible with ValentyUSB.
	in_ep_pid_write(1);

	// If this isn't a standard request, STALL it.
	if (type != REQUEST_TYPE_STANDARD) {
		stall_request();
		return;
	}

	// Handle a subset of standard requests.
	switch (last_setup_packet.bRequest) {

		case REQUEST_SET_ADDRESS:
			handle_set_address();
			break;

		case REQUEST_GET_DESCRIPTOR:
			handle_get_descriptor();
			break;

		case REQUEST_SET_CONFIGURATION:
			handle_set_configuration(last_setup_packet.wValue);
			break;

		default:
			unhandled_request();
			break;
	}
}

//
// Core application.
//

int main(void)
{
	uart_puts("eptri demo started! (built: " __TIME__ ")\n");
	uart_puts("Connecting USB device...\n");
	controller_connect_write(1);
	uart_puts("Connected.\n");


	while (1) {

		// Loop constantly between reading setup packets and handling them.
		read_setup_request();
		handle_setup_request();

	}
}
