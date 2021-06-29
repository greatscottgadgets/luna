#
# This file is part of LUNA.
#

SOC = tinyusb_soc.py

# By default, build our SDK.
all: soc.bit soc.ld resources.h

.PHONY: clean program reprogram flash-soc configure

#
# SDK contents.
#

soc.ld: $(SOC)
	./$(SOC) --generate-ld-script > $@

resources.h: $(SOC)
	./$(SOC) --generate-c-header > $@

soc.bit: $(SOC)
	./$(SOC) -o soc.bit

#
# Helpers.
#

# Load our SoC onto the FPGA...
configure: $(SOC)
	./$(SOC)

# Flash the FPGA's ROM with our SoC.
flash-soc: $(SOC)
	./$(SOC) --flash

clean:
	rm -f $(TARGET).elf $(TARGET).bin soc.ld resources.h soc.bit

