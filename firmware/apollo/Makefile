#
# Apollo debug controller firmware
#

BOARD = luna

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
	-g

INC += \
	src \
	$(TOP)/hw \
	$(TOP)/hw/mcu/microchip/samd/asf4/samd51/hpl/tc/ \

SRC_C += \
	hw/mcu/microchip/samd/asf4/samd21/hal/src/hal_adc_sync.c \
	hw/mcu/microchip/samd/asf4/samd21/hpl/adc/hpl_adc.c

# Build using all 'c' files in the src directory.
SOURCES += $(wildcard src/*.c)
SRC_C += $(addprefix $(CURRENT_PATH)/, $(SOURCES))


# For now, take advantage of the example rules.
include $(TINYUSB_PATH)/examples/rules.mk

dfu: _build/build-$(BOARD)/$(BOARD)-firmware.bin
	dfu-util -a 0 -d 16d0:05a5 -D $<
