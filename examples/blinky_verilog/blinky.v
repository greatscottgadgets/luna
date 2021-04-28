/**
 * Simple, verilog blinky to test the FPGA.
 *
 * Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
 * SPDX-License-Identifier: BSD-3-Clause
 */

module top(input clk_60mhz, output [5:0] led, output [1:0] user_io);

	 reg [26:0] div = 0;

	 always @ ( posedge clk_60mhz ) begin
	 	div <= div + 1'b1;
	 end

     // we invert here as the leds are pull down for on
	 assign led = ~div[26:21];
	 assign user_io = div[25:24];

endmodule
