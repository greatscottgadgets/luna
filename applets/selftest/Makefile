#
# This file is part of LUNA.
#

TARGET  = selftest

CROSS  ?= riscv64-unknown-elf-

CC      = $(CROSS)gcc
OBJCOPY = $(CROSS)objcopy

CFLAGS  = -march=rv32i -mabi=ilp32 -g -Os -Iinclude -ffreestanding -ffunction-sections -fdata-sections
LDFLAGS = -Tsoc.ld -T$(TARGET).ld -nostartfiles -ffreestanding -Wl,-M -Wl,--gc-sections

SOC = $(TARGET)_soc.py
SOURCES = \
	start.S \
	$(TARGET).c \
	uart.c \
	ulpi.c \
	platform.c


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

.PHONY: clean program console

clean:
	rm -f $(TARGET).elf $(TARGET).bin soc.ld resources.h

# Loads our "Hello world" program onto the FPGA.
program: $(TARGET).bin $(SOC)
	./$(SOC)


# Loads our "Hello world" program onto the FPGA.
console: $(TARGET).bin $(SOC)
	./$(SOC) --console

