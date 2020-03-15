#
# Build specifics for LUNA hardware.
#

INC += \
	$(TOP)/hw/mcu/microchip/samd/asf4/samd51/hpl/tc/ \

SRC_C += \
	hw/mcu/microchip/samd/asf4/samd21/hal/src/hal_adc_sync.c \
	hw/mcu/microchip/samd/asf4/samd21/hpl/adc/hpl_adc.c
