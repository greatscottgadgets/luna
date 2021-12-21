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
   Trellis <https://github.com/YosysHQ/prjtrellis>`__ ECP5 tools, the
   `yosys <https://github.com/YosysHQ/yosys>`__ synthesis suite, and the
   `NextPNR <https://github.com/YosysHQ/nextpnr>`__ place-and-route
   tool. All of these tools must be built from ``master``.
-  A working installation of
   `Amaranth HDL <https://github.com/amaranth-lang/amaranth>`__.

Installation
------------

Currently, the LUNA library is considered a “work-in-progress”; and
thus it’s assumed you’ll want to use a local copy of LUNA for
development.

The easiest way to set this up is to install the distribution in a virtual environment.
From the root of the repository:

.. code:: sh

   # Pull down poetry, our build system.
   pip3 install poetry --user

   # Install a copy of our local tools into our virtualenv.
   poetry install


If you want to install LUNA to your machine globally (not recommended), you can do so
using the following single command:


.. code:: sh

   # Create a LUNA package, and install it.
   pip3 install . --user


Testing
-------

The easiest way to test your installation is to build one of the test
applets. These applets are just Python scripts that construct and
program gateware using Amaranth HDL; so they can be run like any other script:

.. code:: sh

   # With GSG or self-built LUNA hardware connected; we can run the full test,
   # and test both our installation and the attached hardware.
   poetry run applets/interactive-test.py

   # Without LUNA hardware connected, we'll only build the applet, to exercise
   # our toolchain.
   poetry run applets/interactive-test.py --dry-run


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
