# Saturn-V Bootloader

## A DAFU-Variant DFU Bootloader
_ for LUNA, and equivalent boards_

Based on [opendime/DAFU/](https://github.com/opendime/)
Based on [t2-firmware/boot/](https://github.com/tessel/t2-firmware)

Compatible with [DFU Utils](http://dfu-util.sourceforge.net/) and [pyfwup](http://github.com/usb-tools/pyfwup).

### Code Origins
This code is a modified variant of the DAFU bootloader; a DFU bootloader for SAMD21-family microcontrollers.

## Background

Saturn-V is the "recovery mode" (RCM) bootloader for LUNA. It's used to bootstrap an entire LUNA board;
and can help to recover the Debug Controller (DC) if the rest of the firmware is lost (or being developed!).

Typically, the Saturn-V bootloader will be used to flash the Apollo firmware onto the Debug Controller; which
can then be usd to bring up the main FPGA gateware.

## Use

Compilation should be as easy as running the single `Makefile`. If you're not using the `arm-none-eabi-` toolchain,
you'll need to specify your compiler prefix using the `CROSS` variable.

Once the bootloader has been built, use an SWD programmer to load the .elf file; or program the relevant .bin
to the start of ROM (0x00000000).
