#
# This file is part of LUNA.
#

TARGET      = eptri_example
BAUDRATE    = 115200
SERIALPORT ?= /dev/ttyACM0

CROSS  ?= riscv64-unknown-elf-

CC      = $(CROSS)gcc
OBJCOPY = $(CROSS)objcopy

CFLAGS  = -march=rv32i -mabi=ilp32 -g -Os -Wall -Werror
LDFLAGS = -Tsoc.ld -Triscv_standalone.ld  -nostdlib

SOC = eptri_device.py
SOURCES = \
	start.S \
	$(TARGET).c


# By default, build our binary.
all: $(TARGET).bin


#
# Generated files.
#

soc.ld: $(SOC)
	./$(SOC) --generate-ld-script > $@

resources.h: $(SOC)
	./$(SOC) --generate-c-header > $@


#
# Firmware binary.
#

$(TARGET).elf: $(SOURCES) soc.ld resources.h
	$(CC) $(CFLAGS) $(LDFLAGS) $(SOURCES) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@


#
# Virtual/command targets.
#

.PHONY: clean program

clean:
	rm -f $(TARGET).elf $(TARGET).bin soc.ld resources.h soc.bit


soc.bit: $(SOC) $(TARGET).bin
	./$(SOC) -o soc.bit

# Load our SoC onto the FPGA...
program: soc.bit
	apollo configure soc.bit
