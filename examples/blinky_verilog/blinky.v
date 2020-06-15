/**
 * Simple, verilog blinky to test the FPGA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

module top(input clk_60mhz, output [5:0] led, output [3:0] user_io);

	 reg [24:0] div = 0;

	 always @ ( posedge clk_60mhz ) begin
	 	div <= div + 1'b1;
	 end

	 assign led = div[24:19];
	 assign user_io = div[24:21];

endmodule
