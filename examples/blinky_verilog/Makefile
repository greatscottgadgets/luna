PROJ=blinky
FPGA_IDCODE=0x21111043

all: ${PROJ}.svf ${PROJ}.bit

%.json: %.v
	yosys -p "synth_ecp5 -json $@" $<

%_out.config: %.json
	nextpnr-ecp5 --json $< --textcfg $@ --25k --package CABGA256 --lpf ${PROJ}.lpf

%.bit: %_out.config
	ecppack --idcode $(FPGA_IDCODE) --input $< --bit $@ # --compress

%.svf: %_out.config
	ecppack --input $< --svf $@ --idcode $(FPGA_IDCODE)

prog: ${PROJ}.bit
	tinyprog -p $<
	
.PRECIOUS: ${PROJ}.json ${PROJ}_out.config
