
=========================
LUNA On Your Own Hardware
=========================

The LUNA stack is designed to be easy to use on your own FPGA hardware -- if you can already run Amaranth designs
on your board, all you'll need is to set up some I/O definitions and some clock domains.

The exact platform requirements depend on how you'll perform USB interfacing, and are detailed below.


High-Speed via a ULPI PHY
-------------------------

Using a ULPI PHY is relatively straightforward; and typically requires no hardware beyond the ULPI PHY. LUNA works with
both designs that receive their ``usb``-domain clocks from the PHY (typical) and designs that provide a 60MHz clock to
their PHY.

The following clock domains are required:

.. list-table::
    :header-rows: 1
    :widths: 1 1 5

    * - Domain Name
      - Frequency
      - Description
    * - ``usb``
      - 60 MHz
      - Core clock for the PHY's clock domain. *Can be provided to the FPGA by the PHY, or provided to the PHY by the FPGA.*
        *See below.*


An I/O resource with the following subsignals is required:


.. list-table::
    :header-rows: 1
    :widths: 1 1 1 6

    * - Subsignal Name
      - Width
      - Direction
      - Description
    * - ``clk``
      - 1
      - input *or* output
      - The ULPI bus clock. Should be configured as an input if the PHY is providing our clock
        (typical), or as an output if the FPGA will provide the clock to the PHY.
    * - ``data``
      - 8
      - bidirectional
      - The bidirectional data bus.
    * - ``dir``
      - 1
      - input
      - The ULPI *direction* signal.
    * - ``nxt``
      - 1
      - input
      - The ULPI *next* signal.
    * - ``stp``
      - 1
      - output
      - The ULPI *stop* signal.
    * - ``rst``
      - 1
      - output
      - The ULPI *reset* signal. The gateware asserts this signal when the PHY should be reset;
        if the PHY requires an active-low reset, this can be inverted with ``PinsN``.


An example resource might look like:

.. code-block:: python

    # Targeting the USB3300 PHY, which provides our clock.
    Resource("ulpi", 0,
            Subsignal("data",  Pins(data_sites,  dir="io")),
            Subsignal("clk",   Pins(clk_site,    dir="i" )),
            Subsignal("dir",   Pins(dir_site,    dir="i" )),
            Subsignal("nxt",   Pins(nxt_site,    dir="i" )),
            Subsignal("stp",   Pins(stp_site,    dir="o" )),
            Subsignal("rst",   Pins(reset_site,  dir="o" )),
            Attrs(IO_TYPE="LVCMOS33")
        )


Full-Speed using FPGA I/O
-------------------------

LUNA provides a *gateware PHY* that enables an FPGA to communicate at Full Speed using only FPGA 3V3 I/O
and a pull-up resistor. The FPGA must be able to provide stable 48 MHz and 12 MHz clocks.

The following clock domains are required:

.. list-table::
    :header-rows: 1
    :widths: 1 1 5

    * - Domain Name
      - Frequency
      - Description
    * - ``usb``
      - 12 MHz
      - Core clock for USB data. Ticks at the USB bitrate of 12MHz, and drives most of the USB logic.
    * - ``usb_io``
      - 48 MHz
      - Edge clock for the USB I/O. Used at the I/O boundary for clock recovery and NRZI encoding.


An I/O resource with the following subsignals is required:

.. list-table::
    :header-rows: 1
    :widths: 1 1 1 6

    * - Subsignal Name
      - Width
      - Direction
      - Description
    * - ``d_p``
      - 1
      - bidirectional
      - The raw USB D+ line; must be on a 3.3V logic bank.
    * - ``d_n``
      - 1
      - bidirectional
      - The raw USB D- line; must be on a 3.3V logic bank.
    * - ``pullup``
      - 1
      - output
      - Control for the USB pull-up resistor; should be connected to D+ via a 1.5k resistor.
    * - ``vbus_valid``
      - 1
      - input
      - *Optional*. If provided, this signal will be used for VBUS detection logic; should be asserted whenever
        VBUS is present. Many devices are "bus-powered" (receive their power from USB), and thus have no need
        for VBUS detection, in which case this signal can be omitted.


An example resource might look like:

.. code-block:: python

    Resource("usb", 0,
        Subsignal("d_p",    Pins("A4")),
        Subsignal("d_n",    Pins("A2")),
        Subsignal("pullup", Pins("D5", dir="o")),
        Attrs(IO_STANDARD="SB_LVCMOS"),
    ),
