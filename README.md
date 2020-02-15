
# LUNA -- a USB-hacking multitool [![Build Status](https://travis-ci.org/greatscottgadgets/luna.svg?branch=master)](https://travis-ci.org/greatscottgadgets/luna) [![GitHub license](https://img.shields.io/github/license/greatscottgadgets/luna.svg)](https://github.com/greatscottgadgets/luna/blob/master/LICENSE.txt)

This is an early work-in-progress version of a USB multitool. It's not recommended that you use or build LUNA, currently -- for all intents and purposes, consider LUNA as "not yet working".

LUNA hardware development is nearing a point where it may serve as a useful platform for early community developers; this README will be updated when second-iteration boards are received and tested.

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
