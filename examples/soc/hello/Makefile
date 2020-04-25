#
# This file is part of LUNA.
#

TARGET  = hello_world

CROSS  ?= riscv64-unknown-elf-

CC      = $(CROSS)gcc
OBJCOPY = $(CROSS)objcopy

CFLAGS  = -march=rv32i -mabi=ilp32 -g -Os -Iinclude
LDFLAGS = -Tsoc.ld -T$(TARGET).ld  -nostdlib

SOC = $(TARGET)_soc.py
SOURCES = \
	start.S \
	hello_world.c


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

# Loads our "Hello world" program onto the FPGA.
program: $(TARGET).bin $(SOC)
	./$(SOC)

