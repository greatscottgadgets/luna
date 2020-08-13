#
# Build specifics for Daisho hardware.
#

# This is an external board, so its identity is determined by its revision number.
# MAJOR = external board
# MINOR = 0 (Daisho)
BOARD_REVISION_MAJOR := 255
BOARD_REVISION_MINOR := 0

# The LPC11uxx libraries have cases where case statements fall through; but no
# comment indicating that the fallthrough is intended. We'll disable the warning.
CFLAGS += -Wno-implicit-fallthrough

SRC_C += \
	hw/mcu/nxp/lpcopen/lpc11uxx/lpc_chip_11uxx/src/ssp_11xx.c \
	hw/mcu/nxp/lpcopen/lpc11uxx/lpc_chip_11uxx/src/i2cm_11xx.c
