
# LUNA -- a USB-hacking multitool [![Build Status](https://travis-ci.org/greatscottgadgets/luna.svg?branch=master)](https://travis-ci.org/greatscottgadgets/luna) [![GitHub license](https://img.shields.io/github/license/greatscottgadgets/luna.svg)](https://github.com/greatscottgadgets/luna/blob/master/LICENSE.txt)

This is an early work-in-progress version of a USB multitool. LUNA isn't yet suited for end-users; but hardware development has reached a point where current-revision boards (r0.2+) make good development platforms for early community developers.

Building this board yourself isn't for the faint of heart -- as it requires placing two BGA components, including a large FPGA. Still, if you're proficient with rework and FPGA development, feel free to join in the fun!

## Project Structure

This project is broken down into several directories:

* `luna` -- the primary LUNA python toolkit; generates gateware and provides USB functionality
  * `luna/apollo`   -- host-python submodule for communicating via the Debug Controller
  * `luna/commands` -- utilities for working with LUNA boards; including for using the debug controller to load FPGA gateware
  * `luna/gateware` -- the core gateware components for LUNA; and utilities for stitching them together
* `firmware` -- firmware for the LUNA debug controller
* `examples` -- simple LUNA-related examples; mostly gateware-targeted, currently
* `applets` -- pre-made gateware applications that provide useful functionality on their own (e.g. are more than examples)

## Project Documentation

LUNA is in early development; and does not yet have user-facing documentation. Early developer documentation is either inlined in the source; or captured in the GitHub wiki.
