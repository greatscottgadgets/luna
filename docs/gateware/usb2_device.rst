
============================
Core USB 2.0 Device Gateware
============================

The *LUNA* gateware library provides a flexible base *USB Device* model, which is designed to provide the basis
for creating both application-specific and general-purpose USB hardware.

USB devices are created using two core components:

* A :class:`USBDevice` instance, which provides hardware that handles low-level USB communications, and which is
  designed to be applicable to all devices; and
* One or more *endpoint interfaces*, which handle high-level USB communications -- and provide the logic
  the tailors the device to its intended application.

The ``USBDevice`` communicates with low-level transciever hardware via the FPGA-friendly *USB Transceiver*
*Macrocell Interface* (UTMI). Translators can be used to transparently adapt the FPGA interface to other
common bus formats; including the common ULPI low-pin-count variant of UTMI.

.. figure:: USBDevice.svg
   :alt: USB 2.0 architecture diagram

   The overall architecture of a LUNA USB 2.0 device, highlighting the ``USBDevice`` components, their
   connections to the *endpoint interfaces*, and optional *bus translator*.


Conceptual Components
---------------------

The ``USBDevice`` class contains the low-level communications hardware necessary to implement a USB device;
including hardware for maintaining device state, detecting events, reading data from the host, and generating
responses.

Token Detector
==============

The *Token Detector* detects *token packets* from the host; and is responsible for:

* Detecting *start of frame* packets, which are used to maintain consistent timing across USB devices.
* Detecting the start of USB *transactions*.
* Identifying the *device* and *endpoint* to which each transaction is addressed.

As each USB transaction starts with a token packet; it is implicitly the Token Detector's responsiblity
to notify endpoint interfaces of imminent incoming data (``OUT`` transactions) and requests for data (``IN``
transactions).


Handshake Detector
==================

The *Handshake Detector* detects *handshake packets* from the host; and is responsible for
identifying the host's response to packets from the device -- indicating whether the host
successfully received a packet sent from the device.


Data Packet Receiver
=====================

The *Data Packet Receiver* is responsible for receiving data packets from the device -- including
the payloads of both ``OUT`` and ``SETUP`` transactions -- and translating them to a simple data stream.

The Data Receiver handles error detection; and thus validates the checksums of each packet using the
Data CRC Unit.


Device State Manager
====================

The *Device State Manager* is responsible for storing global device state -- primarily, the
device's current *address* and *configuration*. The device state manager accepts changes to
the device's address/configuration from each endpoint interface; and automatically resets the
relevant parameters when a USB reset is received.


Handshake Generator
===================

The *Handshake Generator* provides a simple, strobe-based interface that allows endpoints to
easily emit handshake packets -- allowing the device to acknowledge packets (ACK), issue stalls
(STALL) , and to rate limit communications (NAK/NYET).


Data Packet Transmitter
=======================

The *Data Packet Generator* is responsible for generating outgoing USB packets from simple data
streams; including emitting data packet IDs, sending data, and appending data CRCs. This class
automatically appends the required data CRC-16s.


Data CRC Unit
=============

The *Data CRC Unit* is shared among the packet receiver and packet generator; and handles computing
the CRC-16 for USB data streams.


Interpacket Timer
=================

The *Interpacket Timer* is responsible for maintaining maximum and minimum interpacket delays; ensuring
that the device can correctly provide bus turnover times; and knows the window in which handshake packets
are expected to arrive.


Reset/Suspend Sequencer
=======================

The *Reset/Suspend Sequencer* is responsible for detecing USB reset and suspend events; and where applicable,
participating in the USB reset protocol's high-speed detection handshake.

The sequencer:

* Detects USB resets; and communicates to the Device State Manager that it should return the device to an
  un-addressed, un-configured state.
* Performs the *high speed detection handshake*, which allows the device to switch to High Speed operation;
  and thus is necessary for the device to operate at high speed.
* Manages the high-speed terminations; as part of the reset-handshake and suspend protocols.
* Detects the periods of inactivity that indicate the device is being suspended; and automatically disengages
  high-speed terminations while the device is in suspend.



``usb2.device`` Components
--------------------------

.. automodule :: luna.gateware.usb.usb2.device
  :members:
  :show-inheritance:


``usb2.packet`` Components
--------------------------

.. automodule :: luna.gateware.usb.usb2.packet
  :members:
  :show-inheritance:


``usb2.reset`` Components
--------------------------

.. automodule :: luna.gateware.usb.usb2.reset
  :members:
  :show-inheritance:


