===============
Getting Started
===============

Setting up a Build Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This guide highlights the installation / setup process for the LUNA
gateware library. It focuses on getting the Python module (and
prerequisites) up and running.


Prerequisites
-------------

-  Python 3.9, or later.
-  A working FPGA toolchain. We only officially support a toolchain
   composed of the `Project
   Trellis <https://github.com/YosysHQ/prjtrellis>`__ ECP5 tools, the
   `yosys <https://github.com/YosysHQ/yosys>`__ synthesis suite, and the
   `NextPNR <https://github.com/YosysHQ/nextpnr>`__ place-and-route
   tool. You can obtain the latest binary distribution of this
   software from the `oss-cad-suite-build <https://github.com/YosysHQ/oss-cad-suite-build>`__
   project.
-  A working installation of
   `Amaranth HDL <https://github.com/amaranth-lang/amaranth>`__.


Installation
------------

Currently, the LUNA library is considered a “work-in-progress”; and
thus it’s assumed you’ll want to use a local copy of LUNA for
development.

.. code:: sh

    # clone the LUNA repository
    git clone https://github.com/greatscottgadgets/luna.git

The easiest way to set this up is to install the distribution in your working environment.
From the root of the repository:

.. code:: sh

   # Install a copy of our local tools.
   pip install .

   # Alternatively: install all dependencies,
   # including optional development packages (required for running applets and examples).
   pip install .[dev]

If you want to install LUNA to your machine globally (not recommended), you can do so
using the following single command:

.. code:: sh

   # Create a LUNA package, and install it.
   pip install . --user


Testing
-------

The easiest way to test your installation is to build one of the test
applets. These applets are just Python scripts that construct and
program gateware using Amaranth HDL; so they can be run like any other script:

.. code:: sh

   # With GSG or self-built Cynthion hardware connected; we can test both our
   # installation and the attached hardware.
   python applets/bulk_speed_test.py

   # Without hardware connected, we'll only build the applet, to exercise
   # our toolchain.
   python applets/bulk_speed_test.py --dry-run
