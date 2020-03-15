#
# Apollo debug controller firmware
#

# By default, assume LUNA hardware.
# Allow this to be overridden so we can run Apollo on other debug controllers.
BOARD ?= luna

# These should default to the latest revision; but can be set on the command line.
BOARD_REVISION_MAJOR ?= 0
BOARD_REVISION_MINOR ?= 2

# Path to the TINYUSB library.
TINYUSB_PATH = ../lib/tinyusb

# Detect intercept-cc before we build.
ifeq ($(CC), intercept-cc)
	USE_INTERCEPT_CC := yes
endif

# Include the tinyusb basis BSP.
include $(TINYUSB_PATH)/tools/top.mk
include $(TINYUSB_PATH)/examples/make.mk

# If we're using intercept-build, override our compiler back to intercept-cc.
ifeq ($(USE_INTERCEPT_CC), yes)
	CC := intercept-cc
endif

CFLAGS += \
	-Wno-unused-parameter \
	-fstrict-volatile-bitfields \
	-D_BOARD_REVISION_MAJOR_=$(BOARD_REVISION_MAJOR) \
	-D_BOARD_REVISION_MINOR_=$(BOARD_REVISION_MINOR) \
	-g

INC += \
	src \
	src/boards/$(BOARD) \
	$(TOP)/hw \


# Include our per-board make definitions.
include src/boards/$(BOARD)/board.mk

# Build using all 'c' files in our source directories.
SOURCES += $(wildcard src/*.c src/boards/$(BOARD)/*.c)
SRC_C += $(addprefix $(CURRENT_PATH)/, $(SOURCES))

# For now, take advantage of the example rules.
include $(TINYUSB_PATH)/examples/rules.mk


# Flashing using Saturn-V.
dfu: _build/build-$(BOARD)/$(BOARD)-firmware.bin
	dfu-util -a 0 -d 16d0:05a5 -D $<


# Flashing using the Black Magic Probe,
BMP_SERIAL ?= /dev/ttyACM0
bmp: _build/build-$(BOARD)/$(BOARD)-firmware.elf
	arm-none-eabi-gdb -nx --batch \
	-ex 'target extended-remote $(BMP_SERIAL)' \
	-ex 'monitor swdp_scan' \
	-ex 'attach 1' \
	-ex 'load' \
	-ex 'kill' \
	$<
