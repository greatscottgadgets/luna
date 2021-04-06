==========================
Self-made Hardware Bringup
==========================

This guide is intended to help you bring up a LUNA board you’ve built
yourself. If you’ve received your board from Great Scott Gadgets, it
should already be set up, and you shouldn’t need to follow these steps.

Prerequisites
-------------

-  A LUNA board with a populated *Debug Controller* microprocessor. This
   is the SAMD microcontroller located in the Debug section at the
   bottom of the board.
-  A programmer capable of uploading firmware via SWD. Examples include
   the `Black Magic
   Probe <https://github.com/blacksphere/blackmagic>`__; the `Segger
   J-Link <https://www.segger.com/products/debug-probes/j-link/>`__, and
   many `OpenOCD compatible
   boards <http://openocd.org/doc/html/Debug-Adapter-Hardware.html>`__.
-  A toolchain capable of building binaries for Cortex-M0 processors,
   such as the `GNU Arm
   Embedded <https://developer.arm.com/tools-and-software/open-source-software/developer-tools/gnu-toolchain/gnu-rm>`__
   toolchain. If you’re using Linux or macOS, you’ll likely want to
   fetch this using a package manager; a suitable toolchain may be
   called something like ``arm-none-eabi-gcc``.
-  A DFU programming utility, such as
   `dfu-util <http://dfu-util.sourceforge.net/>`__.

Bring-up Process
----------------

The high-level process for bringing up your board is as follows:

1. Compile and upload the *Saturn-V* bootloader, which allows Debug
   Controller to program itself.
2. Compile and upload the *Apollo* Debug Controller firmware, which
   allows FPGA configuration & flashing; and provides debug interfaces
   for working with the FPGA.
3. Install the ``luna`` tools, and run through the self-test procedures
   to validate that your board is working.

Build/upload Saturn-V
---------------------

The “recovery mode (RVM)” bootloader for LUNA boards is named
*Saturn-V*; as it’s the first stage in “getting to LUNA”. The bootloader
is located in [in its own repository](https://github.com/greatscottgadgets/saturn-v).

You can clone the bootloader using `git`:

.. code:: sh

   $ git clone https://github.com/greatscottgadgets/saturn-v


Build the DFU bootloader by invoking ``make``. An example invocation
for modern LUNA hardware might look like:

.. code:: sh

   $ cd saturn-v
   $ make

If you're building a board that predates r0.3 hardware, you'll need to specify
the board you're building for:


.. code:: sh

   $ cd saturn-v
   $ make BOARD=luna_d21


The build should yield two useful build products: ``bootloader.elf`` and
``bootloader.bin``; your SWD programmer will likely consume one of these
two files.

Next, connect your SWD programmer to the header labeled ``uC``, and
upload bootloader image. If you’re using the Black Magic Probe, this
might look like:

.. code:: sh

   $ arm-none-eabi-gdb -nx --batch \
       -ex 'target extended-remote /dev/ttyACM0' \
       -ex 'monitor swdp_scan' \
       -ex 'attach 1' \
       -ex 'load' \
       -ex 'kill' \
       bootloader.elf

If your programmer works best with ``.bin`` files, be sure to upload the
``bootloader.bin`` to the start of flash (address ``0x00000000``).

Once the bootloader is installed, you should see LED ``A`` blinking
rapidly. This is the indication that your board is in Recovery Mode
(RVM), and can be programmed via DFU.

You can verify that the board is DFU-programmable by running
``dfu-util``:

.. code:: sh

   $ dfu-util --list

If your device shows up as a LUNA board, congratulations! You’re ready
to move on to the next step.

Optional: Bootloader Locking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optionally, you can reversibly lock the bootloader region of the Debug
Controller, preventing you from accidentally overwriting the bootloader.
This is most useful for users developing code for the Debug Controller.

If you choose to lock the bootloader, you should lock the first ``4KiB``
of flash. Note that currently, the bootloader lock feature of *Black
Magic Probe* devices always locks ``8KiB`` of flash; and thus cannot be
used for LUNA.

Build/upload Apollo
-------------------

The next bringup step is to upload the *Apollo* Debug Controller
firmware, which will provide an easy way to interface with the board’s
FPGA and any gateware running on it. The Apollo source is located
[in its own repository](https://github.com/greatscottgadgets/apollo).

You can clone the bootloader using `git`:

.. code:: sh

   $ git clone https://github.com/greatscottgadgets/apollo



You can build and run the firmware in one step by invoking ``make``. In
order to ensure your firmware matches the hardware it’s running on,
you’ll need to provide the hardware revision using the
``BOARD_REVISION_MAJOR`` and ``BOARD_REVISION_MINOR`` make variables.

The board’s hardware revision is printed on its silkscreen in a
``r(MAJOR).(MINOR)`` format. Board ``r0.2`` would have a
``BOARD_REVISION_MAJOR=0`` and a ``BOARD_REVISION_MINOR=2``. If your
board’s revision ends in a ``+``, do not include it in the revision
number.

An example invocation for a ``r0.2`` board might be:

.. code:: sh

   $ make BOARD_REVISION_MAJOR=0 BOARD_REVISION_MINOR=2 dfu

Once programming is complete, only LED ``E`` should be blinking;
indicating that the Apollo firmware is idle.

Running Self-Tests
------------------

The final step of bringup is to validate the functionality of your
hardware. This is most easily accomplished by running LUNA’s interactive
self-test applet.

Before you can run the applet, you’ll need to have a working ``luna``
development environment. See [[Setting up the development environment]]
to get your environment set up.

Next, we can check to make sure your LUNA board is recognized by the
LUNA toolchain. Running the ``apollo info`` command will list any
detected devices:

.. code:: sh

   $ apollo info
   Detected a LUNA device!
       Hardware: LUNA r0.2
       Serial number: <snip>

Once you’ve validated connectivity, you’re ready to try running the
``interactive-test`` applet. From the root of the repository:

.. code:: sh

   $ python3 applets/interactive-test.py


Troubleshooting
---------------

**Issue: some of the build files weren't found;** ``make`` **produces a message like "** ``no rule to make target`` **".**

Chances are, your clone of LUNA is was pulled down without its
submodules. You can pull down the relevant submodules using ``git``:

.. code:: sh

   $ git submodule update --init --recursive

**Issue: the ``apollo info`` command doesn't see a connected board.**

On Linux, this can be caused by a permissions issue. Check first for the
presence of your device using ``lsusb``; if you see a device with the
VID/PID ``1d50:615c``, your board is present – and you likely have a
permissions issue. You’ll likely need to install permission-granting
udev rules.
