#!/usr/bin/env python3

import usb.core

IN_REQUEST  = usb.ENDPOINT_IN  | usb.RECIP_DEVICE | usb.TYPE_VENDOR
OUT_REQUEST = usb.ENDPOINT_OUT | usb.RECIP_DEVICE | usb.TYPE_VENDOR

VENDOR_REQUEST_READ_RAIL = 0xe0

d = usb.core.find(idVendor=0x1d50, idProduct=0x60e7)

# start JTAG
x = d.ctrl_transfer(IN_REQUEST, VENDOR_REQUEST_READ_RAIL, data_or_wLength=2)
print(x)
