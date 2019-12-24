#
# Apollo debug controller firmware
#

BOARD = luna

# Path to the TINYUSB library.
TINYUSB_PATH = ../lib/tinyusb

# Include the tinyusb basis BSP.
include $(TINYUSB_PATH)/tools/top.mk
include $(TINYUSB_PATH)/examples/make.mk

INC += \
	src \
	$(TOP)/hw \

# Build using all 'c' files in the src directory.
SOURCES += $(wildcard src/*.c)
SRC_C += $(addprefix $(CURRENT_PATH)/, $(SOURCES))


# For now, take advantage of the example rules.
include $(TINYUSB_PATH)/examples/rules.mk

dfu: _build/build-$(BOARD)/$(BOARD)-firmware.bin
	dfu-util -a 0 -d 1d50:60e7 -D $<
