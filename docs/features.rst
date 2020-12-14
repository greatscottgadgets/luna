
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
	  - :complete:`feature complete`
	* -
	  - super-speed using PIPE PHY
	  - :needstest:`basic support complete; still experimental`
	* -
	  - super-speed using SerDes PHY
	  - :inprogress:`in progress`
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
	  - :complete:`feature complete`
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
	  - ``IN`` transfer helpers
	  - :needstest:`complete; needs examples and testing`
	* -
	  - ``OUT`` transfer helpers
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

The LUNA library is intended to work on any FPGA with sufficient fabric performance and resources; but testing is
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
	  - ULPI x3 (USB3343)
	  - :complete:`Fully Supported`
	* - OpenVizsla USB Analyzer
	  - Spartan 6
	  - ULPI (USB3343)
	  - :complete:`Fully Supported`
	* - LambdaConcept ECPIX-5
	  - ECP5
	  - ULPI (USB3300), SerDes PHY
	  - :complete:`High-Speed Fully Supported` / :inprogress:`Super-Speed In Progress`
	* - TinyFPGA Ex
	  - ECP5
	  - SerDes PHY
	  - :planned:`Planned Super-Speed Device Mode`
	* - Logicbone
	  - ECP5
	  - SerDes PHY
	  - :complete:`Full-Speed Fully Supported` / :inprogress:`Super-Speed In Progress`
	* - Daisho
	  - Cyclone IV
	  - PIPE (TUSB1310A)
	  - :planned:`Planned Super-Speed Device Mode`
	* - PHYWhisperer-USB
	  - Spartan 7
	  - UTMI
	  - :planned:`Planned Device Mode Support`
	* - LambdaConcept USB2Sniffer
	  - Artix 7
	  - ULPI x2 (USB3300)
	  - :complete:`Fully Supported`
	* - OrangeCrab
	  - ECP5
	  - no hardware PHY
	  - :complete:`Full-Speed/Device Mode Support`
	* - ULX3S
	  - ECP5
	  - no hardware PHY
	  - :complete:`Full-Speed/Device Mode Support`
	* - Fomu PVT/Hacker
	  - iCE40 UP
	  - no hardware PHY
	  - :complete:`Full-Speed/Device Mode Support`
	* - Fomu EVT3
	  - iCE40 UP
	  - no hardware PHY
	  - :complete:`Full-Speed/Device Mode Support`
	* - iCEBreaker Bitsy
	  - iCE40 UP
	  - no hardware PHY
	  - :complete:`Full-Speed/Device Mode Support`
	* - Glasgow
	  - iCE40 HX
	  - no hardware PHY
	  - :planned:`Planned Full-Speed Support`
	* - TinyFPGA Bx
	  - iCE40 LP
	  - no hardware PHY
	  - :complete:`Full-Speed/Device Mode Support`
	* - Digilent Nexys Video (SS with add-on board)
	  - Artix 7
	  - FMC for PIPE (TUSB1310A) add-on boards
	  - :complete:`Super-Speed Fully Supported`
	* - Digilent Genesys2 (SS with add-on board)
	  - Kintex 7
	  - ULPI (TUSB1210), FMC for PIPE (TUSB1310A) add-on boards
	  - :complete:`High/Super-Speed Fully Supported`

