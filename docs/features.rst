
================
Status & Support
================

.. role:: planned
.. role:: inprogress
.. role:: needstest
.. role:: complete

The LUNA library is a work in progress; but many of its features are usable enough for inclusion in your own designs.
More testing of our work -- and more feedback -- is always appreciated!

Support for Device Mode
-----------------------

.. list-table::
	:header-rows: 1
	:widths: 1 2 1

	* - Feature
	  -
	  - Status
	* - **USB Communications**
	  - high-/full-speed with ``UTMI`` PHY
	  - :needstest:`complete, needs testing`
	* -
	  - high-/full-speed with ``ULPI`` PHY
	  - :complete:`feature complete`
	* -
	  - full-speed using raw gpio / pull resistors
	  - :inprogress:`mostly working; some features missing`
	* -
	  - super-speed using PIPE PHY
	  - :planned:`planned`
	* -
	  - super-speed using PIPE PHY
	  - :planned:`planned`
	* -
	  - low speed, via ULPI/UTMI PHY
	  - :planned:`untested`
	* -
	  - low speed, using raw gpio / pull resistors
	  - :planned:`unsupported, currently`
	* -
	  -
	  -
	* - **Control Transfers / Endpoints**
	  - user-defined
	  - :complete:`feature complete`
	* -
	  - fully-gateware-implemented, with user vendor request handler support
	  - :needstest:`complete, could use improvements`
	* -
	  - CPU interface
	  - :inprogress:`working; needs more interfaces & examples`
	* -
	  -
	  -
	* - **Bulk Transfers / Endpoints**
	  - user-defined
	  - :complete:`feature complete`
	* -
	  - ``IN`` stream helpers
	  - :complete:`feature complete`
	* -
	  - ``OUT`` stream helpers
	  - :needstest:`complete, could use expansion`
	* -
	  - CPU interface
	  - :inprogress:`working; needs more interfaces & examples`
	* -
	  -
	  -
	* - **Interrupt Transfers / Endpoints**
	  - user-defined
	  - :complete:`feature complete`
	* -
	  - status-to-host helper
	  - :needstest:`complete, needs testing`
	* -
	  - status-from-host helper
	  - :planned:`planned`
	* -
	  - CPU interface
	  - :inprogress:`working; needs more interfaces & examples`
	* -
	  -
	  -
	* - **Isochronous Transfers / Endpoints**
	  - user-defined
	  - :planned:`planned`
	* -
	  - ``IN`` stream helpers
	  - :planned:`planned`
	* -
	  - ``OUT`` stream helpers
	  - :planned:`planned`
	* -
	  - CPU interface
	  - :planned:`planned`
	* -
	  -
	  -
	* - **USB Analysis**
	  - basic analysis
	  - :inprogress:`basic analysis working, in progress`
	* -
	  - full analysis support
	  - :planned:`planned`


Support for Host Mode
-----------------------

The LUNA library currently does not provide any support for operating as a USB host; though the low-level USB
communications interfaces have been designed to allow for eventual host support. Host support is not currently
a priority, but contributions are welcome.


"Reference" Boards
------------------

The LUNA library is intended to work on any FPGA with sufficient fabric performand and resources; but testing is
only performed on a collection of reference boards.

.. list-table::
	:header-rows: 1
	:widths: 4 2 2 2

	* - Board
	  - FPGA Family
	  - PHY
	  - Status
	* - *LUNA* Hardware
	  - ECP5
	  - ULPI x3
	  - :complete:`Fully Supported`
	* - OpenVizsla USB Analyzer
	  - Spartan 6
	  - ULPI
	  - :needstest:`Fully Supported, needs testing`
	* - TinyFPGA Ex
	  - ECP5 SerDes
	  - SerDes PHY
	  - :planned:`Planned Super-Speed Device Mode`
	* - Daisho
	  - Cyclone IV
	  - PIPE
	  - :planned:`Planned Super-Speed Device Mode`
	* - PHYWhisperer-USB
	  - Spartan 7
	  - UTMI
	  - :planned:`Planned Device Mode Support`
	* - LambdaConcept USB Sniffer
	  - Artix 7
	  - ULPI x2
	  - :planned:`Planned Device Mode Support`
	* - OrangeCrab
	  - ECP5
	  - no hardware PHY
	  - :needstest:`Full-Speed/Device Mode Support`
	* - Fomu PVT/Hacker
	  - iCE40 UP
	  - no hardware PHY
	  - :needstest:`Full-Speed/Device Mode Support`
	* - Fomu EVT3
	  - iCE40 UP
	  - no hardware PHY
	  - :needstest:`Full-Speed/Device Mode Support`
	* - Glasgow
	  - iCE40 HX
	  - no hardware PHY
	  - :planned:`Planned Full-Speed Support`
	* - TinyFPGA Bx
	  - iCE40 LP
	  - no hardware PHY
	  - :needstest:`Full-Speed/Device Mode Support,`

