#
# DAFU Makefile
#
# Targets:
#	all - make everything, look for dafu.elf inparticular
#	clean - delete intermediates
#	clobber - delete all build products
#
#
#

CROSS=arm-none-eabi-

# Toolchain
CC      = $(CROSS)gcc
OBJDUMP = $(CROSS)objdump
OBJCOPY = $(CROSS)objcopy
NM      = $(CROSS)nm
SIZE    = $(CROSS)size

# Basename of targets
TARGET_NAME = bootloader

# Hardware configuration. Not so critical. I suspect binary would not change
# for any value here in the D21 family.
PART = SAMD21G18A

# Compiler flags.
CFLAGS = -Wall --std=gnu99 -Os -g3 \
			-flto -fdata-sections -ffunction-sections -funsigned-char -funsigned-bitfields \
			-mcpu=cortex-m0plus -mthumb -D __$(PART)__ -I .

# USB PID/VID and other branding values
CFLAGS += \
			-D USB_PRODUCT_ID=0x7551 \
			-D USB_VENDOR_ID=0x1209 \
			-D USB_MANUFACTURER_STR='"Great Scott Gadgets"' \
			-D USB_PRODUCT_STR='"LUNA Saturn-V RCM Bootloader"' \
			-D COPYRIGHT_NOTE='"Visit https://githib.com/opendime/DAFU"' \

# Header file search path
PRJ_PATH = deps
INC_PATHS = \
			usb \
			sam0/cmsis \
			sam0/include \
			sam0/cmsis/samd21/include \
			sam0/cmsis/samd21/source 

CFLAGS += $(foreach INC,$(addprefix $(PRJ_PATH)/,$(INC_PATHS)),-I$(INC))

# Specialized linker-script here. Not the standard one!
#
LINKER_SCRIPT = link-script.ld

LDFLAGS += -flto -Wl,--gc-sections --specs=nano.specs -Wl,-T$(LINKER_SCRIPT)

C_SRCS = \
			common/startup_samd21.c \
			main.c \
			usb.c \
			common/clock.c \
			deps/usb/class/dfu/dfu.c \
			deps/usb/samd/usb_samd.c \
			deps/usb/usb_requests.c

OBJS = $(addsuffix .o, $(basename $(C_SRCS) $(ASM_SRCS)))

TARGET_ELF = $(TARGET_NAME).elf
TARGETS = $(TARGET_NAME).hex $(TARGET_NAME).lss $(TARGET_NAME).bin $(TARGET_NAME).sym $(TARGET_NAME).o

all: $(TARGETS)

# recompile on any change, because with a small project like this...
$(OBJS): Makefile $(C_SRCS) $(ASM_SRCS)

$(TARGETS): $(TARGET_ELF) Makefile

# link step
$(TARGET_ELF): $(OBJS) $(LINKER_SCRIPT) Makefile
	$(CC) $(CFLAGS) -o $(TARGET_ELF) $(LDFLAGS) $(OBJS)
	$(SIZE) -Ax $@

# detailed listing, very handy
%.lss: $(TARGET_ELF)
	$(OBJDUMP) -h -S $< > $@

# symbol dump, meh
%.sym: $(TARGET_ELF)
	$(NM) -n $< > $@

# intel HEX format
%.hex: $(TARGET_ELF)
	$(OBJCOPY) -O ihex  $< $@

# raw binary
%.bin: $(TARGET_ELF)
	$(OBJCOPY) -O binary $< $@

# a binary of just the ROM area, ready to be linked into another program.
$(TARGET_NAME).o: $(TARGET_ELF)
	$(OBJCOPY) --rename-section .text=.vectors.bootloader \
				--prefix-symbols=dafu_ \
				--pad-to 0x1000 --gap-fill 0xff \
				$(TARGET_ELF) $@
	$(OBJDUMP) -h $@
	$(SIZE) -Ax $@

clean:
	$(RM) $(OBJS)

clobber: clean
	$(RM) $(TARGETS)

debug:
	@echo CFLAGS = $(CFLAGS)
	@echo 
	@echo C_SRCS = $(C_SRCS)
	@echo 
	@echo OBJS = $(OBJS)

tags:
	ctags -f .tags *.[ch] -R deps/sam0 deps/usb common
