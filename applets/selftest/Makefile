#
# This file is part of LUNA.
#

TARGET  = selftest
PORT   ?= /dev/ttyACM0

CROSS  ?= riscv64-unknown-elf-

CC      = python -m ziglang cc
LLD     = python -m ziglang ld.lld
OBJCOPY = $(CROSS)objcopy

CFLAGS  = \
	-target riscv32-freestanding-eabi \
	-march=generic_rv32 \
	-mabi=ilp32 \
	-g \
	-Os \
	-Iinclude \
	-ffreestanding \
	-nostdlib \
	-ffunction-sections \
	-fdata-sections \
	-T$(TARGET).ld

LLDFLAGS = \
	 -T$(TARGET).ld \
	 --gc-sections \
	 --oformat binary \
	 -nostdlib \
	 -static
	
SOC = $(TARGET)_soc.py
#ASM_SOURCES = start.S
SOURCES = \
	start.c \
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
#
$(TARGET).o: $(SOURCES) soc.ld resources.h
	$(CC) $(CFLAGS) $(SOURCES) -c -o $@

$(TARGET).bin: $(TARGET).o
	$(LLD) $(LLDFLAGS) $< -o $@

$(TARGET).bit: $(TARGET).bin $(SOC)
	./$(SOC) --dry-run -o $(TARGET).bit


#
# Virtual/command targets.
#

.PHONY: clean program console

clean:
	rm -f $(TARGET).elf $(TARGET).o $(TARGET).bin $(SOC).bit soc.ld resources.h

# Loads the self-test program onto our FPGA.
program: $(TARGET).bin $(SOC)
	./$(SOC)

# Loads our "Hello world" program onto the FPGA.
run: $(TARGET).bit 
	apollo configure $(TARGET).bit
	pyserial-miniterm $(PORT) 115200
