
# LUNA: a USB multitool & nMigen library ![Simulation Status](https://github.com/greatscottgadgets/luna/workflows/Testbench%20Simulations/badge.svg) [![Documentation Status](https://readthedocs.org/projects/luna/badge/?version=latest)](https://luna.readthedocs.io/en/latest/?badge=latest)

![LUNA r0.2 side view](docs/images/board_readme_side.jpg)

## LUNA Library

LUNA is a full toolkit for working with USB using FPGA technology; and provides hardware, gateware, and software to enable USB applications.

Some things you can use LUNA for, currently:

- **Protocol analysis for Low, Full or High speed USB.** LUNA provides both hardware designs and gateware that allow passive USB monitoring. When combined with the [ViewSB](https://github.com/usb-tools/viewsb) USB analyzer
  toolkit, LUNA hardware+gateware can be used as a full-featured USB analyzer.
- **Creating your own Low, Full or High speed USB device.** LUNA provides a collection of nMigen gateware that allows you to easily create USB devices in gateware, software, or a combination of the two.
- **Building USB functionality into a new or existing System-on-a-Chip (SoC).** LUNA is capable of generating custom peripherals targeting the common Wishbone bus; allowing it to easily be integrated into SoC designs; and the library provides simple automation for developing simple SoC designs.

Some things you'll be able to use LUNA for in the future:

- **Man-in-the-middle'ing USB communications.** The LUNA toolkit will be able to act
  as a *USB proxy*, transparently modifying USB data as it flows between a host and a device.
- **USB reverse engineering and security research.** The LUNA toolkit will serve as an ideal
  backend for tools like [FaceDancer](https://github.com/usb-tools/facedancer); allowing easily
  emulation and rapid prototyping of compliant and non-compliant USB devices.

## LUNA Hardware

The LUNA project also includes eponymous multi-tool hardware. This hardware isn't yet suited for end-users; but hardware development has reached a point where current-revision boards (r0.2+) make good development platforms for early community developers.

Building this board yourself isn't for the faint of heart -- as it requires placing two BGA components, including a large FPGA. Still, if you're proficient with rework and FPGA development, feel free to join in the fun!

## Project Structure

This project is broken down into several directories:

* `luna` -- the primary LUNA python toolkit; generates gateware and provides USB functionality
  * `luna/apollo`   -- host-python submodule for communicating via the Debug Controller
  * `luna/commands` -- utilities for working with LUNA boards; including for using the debug controller to load FPGA gateware
  * `luna/gateware` -- the core gateware components for LUNA; and utilities for stitching them together
* `examples` -- simple LUNA-related examples; mostly gateware-targeted, currently
* `firmware` -- firmware for the LUNA debug controller
* `docs` -- sources for the LUNA Sphinx documentation.
* `contrib` -- contributed/non-core components; such as udev rules
* `applets` -- pre-made gateware applications that provide useful functionality on their own (e.g. are more than examples)

## Project Documentation

LUNA's documentation is captured on [Read the Docs](https://luna.readthedocs.io/en/latest/). Raw documentation sources
are is in the `docs` folder.
