===============
Getting Started
===============

Setting up a Build Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This guide highlights the installation / setup process for the ``luna``
gateware library. It focuses on getting the Python module (and
prerequisites) up and running.

Prerequisites
-------------

-  Python 3.7, or later.
-  A working FPGA toolchain. We only officially support a toolchain
   composed of the `Project
   Trellis <https://github.com/SymbiFlow/prjtrellis>`__ ECP5 tools, the
   `yosys <https://github.com/YosysHQ/yosys>`__ synthesis suite, and the
   `NextPNR <https://github.com/YosysHQ/nextpnr>`__ place-and-route
   tool. All of these tools must be built from ``master``.
-  A working installation of
   `nMigen <https://github.com/nmigen/nmigen>`__. Note that only the
   official toolchain from `@nmigen <https://github.com/nmigen>` is
   supported; the `@m-labs <https://github.com/m-labs>` derivative is
   not.

Installation
------------

Currently, the LUNA library is considered a “work-in-progress”; and
thus it’s assumed you’ll want to use a local copy of LUNA for
development.

The easiest way to set this up is to install the distribution in-place.
From the root of the repository:

.. code:: sh

   # Pull down our requirements.
   pip3 install -r requirements.txt --user

   # Install an "in-place" development copy.
   python3 setup.py develop --user

Testing
-------

The easiest way to test your installation is to build one of the test
applets. These applets are just Python scripts that construct and
program gateware using nMigen; so they can be run like any other script:

.. code:: sh

   # With LUNA hardware connected; we can run the full test, and test both
   # our installation and the attached hardware.
   python3 applets/interactive-test.py

   # Without LUNA hardware connected, we'll only build the applet, to exercise
   # our toolchain.
   python3 applets/interactive-test.py --dry-run

The ``apollo`` utility.
-------------------------

The ``luna`` distribution depends on ``apollo``, which includes a utility
that can be used to perform various simple functions useful in development;
including simple JTAG operations, SVF playback, manipulating the board’s flash,
and debug comms.

.. code:: sh

   $ apollo
   usage: apollo [-h] command: [[argument]] [[value]]

   Utility for LUNA development via an onboard Debug Controller.

   positional arguments:
     command:    info       -- Prints information about any connected LUNA-compatible boards
                 configure  -- Uploads a bitstream to the device's FPGA over JTAG.
                 erase      -- Clears the attached board's configuration flash.
                 program    -- Programs the target bitstream onto the attached FPGA.
                 jtag-scan  -- Prints information about devices on the onboard JTAG chain.
                 flash-scan -- Attempts to detect any attached configuration flashes.
                 svf        -- Plays a given SVF file over JTAG.
                 spi        -- Sends the given list of bytes over debug-SPI, and returns the response.
                 spi-inv    -- Sends the given list of bytes over SPI with inverted CS.
                 spi-reg    -- Reads or writes to a provided register over the debug-SPI.
     [argument]  the argument to the given command; often a filename
     [value]     the value to a register write command

To have easy access to the ``apollo`` command, you’ll need to ensure
that your python binary directory is in your ``PATH``. For macOS/Linux,
this often means adding ``~/.local/bin`` to your ``PATH``.
