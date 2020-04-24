#
# This file is part of LUNA.
#

TARGET      = blinky
BAUDRATE    = 115200
SERIALPORT ?= /dev/ttyACM0

CROSS  ?= riscv64-unknown-elf-

CC      = $(CROSS)gcc
OBJCOPY = $(CROSS)objcopy

CFLAGS  = -march=rv32i -mabi=ilp32 -g -Os
LDFLAGS = -Tsoc.ld -Triscv_application.ld  -nostdlib

SOC = bios_example.py
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
	rm -f $(TARGET).elf $(TARGET).bin soc.ld resources.h


# Load our SoC onto the FPGA...
configure: $(SOC)
	./$(SOC)

# Flash the FPGA's ROM with our SoC.
flash-soc: $(SOC)
	./$(SOC) --flash

# Program the SoC with our application.
program: $(TARGET).bin
	echo -e "\nserialboot" | script -q /dev/null -c \
		"flterm --speed $(BAUDRATE) --kernel $< --kernel-addr $(shell ./$(SOC) --get-fw-address) $(SERIALPORT)"
