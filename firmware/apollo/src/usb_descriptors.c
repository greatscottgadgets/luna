/* 
 * The MIT License (MIT)
 *
 * Copyright (c) 2019 Katherine J. Temkin <kate@ktemkin.com>
 * Copyright (c) 2019 Great Scott Gadgets <ktemkin@greatscottgadgets.com>
 * Copyright (c) 2019 Ha Thach (tinyusb.org)
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 */

#include "tusb.h"

#define SERIAL_NUMBER_STRING_INDEX 3

//--------------------------------------------------------------------+
// Device Descriptors
//--------------------------------------------------------------------+
tusb_desc_device_t const desc_device =
{
	.bLength            = sizeof(tusb_desc_device_t),
	.bDescriptorType    = TUSB_DESC_DEVICE,
	.bcdUSB             = 0x0200,

	// Use Interface Association Descriptor (IAD) for CDC
	// As required by USB Specs IAD's subclass must be common class (2) and protocol must be IAD (1)
	.bDeviceClass       = TUSB_CLASS_MISC,
	.bDeviceSubClass    = MISC_SUBCLASS_COMMON,
	.bDeviceProtocol    = MISC_PROTOCOL_IAD,

	.bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,

	.idVendor           = 0x1d50,
	.idProduct          = 0x60e7, // FIXME: replace with unique Openmoko PID
	.bcdDevice          = 0x0100,

	.iManufacturer      = 0x01,
	.iProduct           = 0x02,
	.iSerialNumber      = SERIAL_NUMBER_STRING_INDEX,

	.bNumConfigurations = 0x01
};

// Invoked when received GET DEVICE DESCRIPTOR
// Application return pointer to descriptor
uint8_t const * tud_descriptor_device_cb(void)
{
	return (uint8_t const *) &desc_device;
}

//--------------------------------------------------------------------+
// Configuration Descriptor
//--------------------------------------------------------------------+

enum
{
	ITF_NUM_CDC = 0,
	ITF_NUM_CDC_DATA,
	ITF_NUM_DFU_RT,
	ITF_NUM_TOTAL 
};

#define CONFIG_TOTAL_LEN    (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_DFU_RT_DESC_LEN)


uint8_t const desc_configuration[] =
{
	// Interface count, string index, total length, attribute, power in mA
	TUD_CONFIG_DESCRIPTOR(ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, TUSB_DESC_CONFIG_ATT_REMOTE_WAKEUP, 100),

	// Interface number, string index, EP notification address and size, EP data address (out, in) and size.
	TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, 0x81, 8, 0x02, 0x82, 64),

	// Interface descriptor for the DFU runtime interface.
	TUD_DFU_RT_DESCRIPTOR(ITF_NUM_DFU_RT, 5, 0x0d, 500, 4096),
};


// Invoked when received GET CONFIGURATION DESCRIPTOR
// Application return pointer to descriptor
// Descriptor contents must exist long enough for transfer to complete
uint8_t const * tud_descriptor_configuration_cb(uint8_t index)
{
	(void) index; // for multiple configurations
	return desc_configuration;
}

//--------------------------------------------------------------------+
// String Descriptors
//--------------------------------------------------------------------+


// array of pointer to string descriptors
char const* string_desc_arr [] =
{
	(const char[]) { 0x09, 0x04 }, // 0: is supported language is English (0x0409)
	"Great Scott Gadgets",         // 1: Manufacturer
	"LUNA Debug Controller",       // 2: Product
	NULL,                          // 3: Serials, should use chip ID
	"UART Bridge",                 // 4: CDC Interface
	"DFU Runtime"                  // 5: DFU Interface
};

static uint16_t _desc_str[34];


/**
 * Returns a USB string descriptor that describes this device's unique ID.
 */ 
static uint16_t *get_serial_number_string_descriptor(void)
{
	const unsigned serial_number_chars = 32;

	int count = 0;

	//
	// Read and save the device serial number as normal Base32.
	//

	// Documented in section 9.3.3 of D21 datasheet, page 32 (rev G), but no header file, 
	// these are not contiguous addresses.
	const uint32_t	*ser[4] = {
		(uint32_t *)0x0080A00C, 
		(uint32_t *)0x0080A040, 
		(uint32_t *)0x0080A044, 
		(uint32_t *)0x0080A048 
	};

	// Populate the length and string type, as these are the first two bytes
	// of our descriptor...
	_desc_str[count++] = (TUSB_DESC_STRING << 8 ) | ((serial_number_chars * 2) + 2);;

	// ... and convert our serial number into hex.
	for (unsigned i = 0; i < 32; ++i) {
		uint32_t word  = *ser[i / 8];
		uint32_t hexit = word >> ((i % 8) * 4);
		_desc_str[count++] = "0123456789abcdef"[hexit & 0xF];
	}

	return _desc_str;
}

// Invoked when received GET STRING DESCRIPTOR request
// Application return pointer to descriptor, whose contents must exist long enough for transfer to complete
uint16_t const* tud_descriptor_string_cb(uint8_t index)
{
	uint8_t chr_count;

	// If we're looking for the "supported languages" descriptor, return it directly.
	if (index == 0) {
		memcpy(&_desc_str[1], string_desc_arr[0], 2);
		chr_count = 1;
	}
	//  If this is a request for the serial number, return the device's unique ID>
	else if (index == SERIAL_NUMBER_STRING_INDEX) {
		return get_serial_number_string_descriptor();
	}

	// Otherwise, take the ASCII string provided and encode it as UTF-16.
	else {

	if ( !(index < sizeof(string_desc_arr)/sizeof(string_desc_arr[0])) ) {
		return NULL;
	}

	const char* str = string_desc_arr[index];

	// Cap at max char
	chr_count = strlen(str);
	if ( chr_count > 31 ) chr_count = 31;

	for(uint8_t i=0; i<chr_count; i++)
	{
		_desc_str[1+i] = str[i];
	}
	}

	// first byte is length (including header), second byte is string type
	_desc_str[0] = (TUSB_DESC_STRING << 8 ) | (2*chr_count + 2);

	return _desc_str;
}
