#
# This file is part of LUNA.
#

TARGET  = selftest
PORT   ?= /dev/ttyACM0

CROSS  ?= riscv64-unknown-elf-

CC      = $(CROSS)gcc
OBJCOPY = $(CROSS)objcopy

CFLAGS  = -march=rv32i -mabi=ilp32 -g -Os -Iinclude -ffreestanding -ffunction-sections -fdata-sections
LDFLAGS = -Tsoc.ld -T$(TARGET).ld -nostartfiles -ffreestanding -Wl,--gc-sections

SOC = $(TARGET)_soc.py
SOURCES = \
	start.S \
	$(TARGET).c \
	platform.c \
	uart.c \
	ulpi.c \
	psram.c


# By default, build our binary.
all: $(TARGET).bit

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

$(TARGET).bit: $(TARGET).bin $(SOC)
	./$(SOC) --dry-run -o $(TARGET).bit


#
# Virtual/command targets.
#

.PHONY: clean program console

clean:
	rm -f $(TARGET).elf $(TARGET).bin $(SOC).bit soc.ld resources.h

# Loads the self-test program onto our FPGA.
program: $(TARGET).bin $(SOC)
	./$(SOC)

# Loads our "Hello world" program onto the FPGA.
run: $(TARGET).bit 
	apollo configure $(TARGET).bit
	miniterm.py $(PORT) 115200
