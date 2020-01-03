# LUNA -- a lightweight USB-hacking multitool

This is an early work-in-progress version of a USB multitool. It's not recommended that you use or build LUNA, currently -- for all intents and purposes, consider LUNA as "not yet working".

## Project Structure

This project is broken down into several directories:

* `luna` -- the primary LUNA python toolkit; generates gateware and provides USB functionality
  * `luna/utilities` -- utilities for working with LUNA boards; including for using the debug controller to load FPGA gateware
* `firmware` -- firmware for the LUNA debug controller
* `examples` -- simple LUNA-related examples; mostly gateware-targeted, currently
