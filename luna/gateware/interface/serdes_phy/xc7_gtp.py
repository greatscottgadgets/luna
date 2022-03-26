#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
#
# Code based in part on ``litex`` and ``liteiclink``.
# SPDX-License-Identifier: BSD-3-Clause
""" Soft PIPE backend for the Xilinx 7 Series GTP transceivers. """

from amaranth import *
from amaranth.lib.cdc import FFSynchronizer


from .xc7           import DRPInterface, DRPArbiter, DRPFieldController
from .xc7           import GTResetDeferrer, GTPRXPMAResetWorkaround, GTOOBClockDivider
from .lfps         import LFPSSquareWaveGenerator, LFPSSquareWaveDetector
from ..pipe        import PIPEInterface


Open = Signal


class GTPQuadPLL(Elaboratable):
    def __init__(self, refclk, refclk_freq, linerate, channel=0):
        assert channel in [0, 1]
        self.channel     = channel

        self._refclk      = refclk
        self._refclk_freq = refclk_freq
        self._linerate    = linerate

        self.config  = self.compute_config(refclk_freq, linerate)

        #
        # I/O ports
        #
        self.clk     = Signal()
        self.refclk  = Signal()
        self.reset   = Signal()
        self.lock    = Signal()
        self.drp     = DRPInterface()


    def elaborate(self, platform):
        gtpe2_params = dict(
            # Common Block Attributes
            p_BIAS_CFG          = 0x0000000000050001,
            p_COMMON_CFG        = 0x00000000,

            # PLL Attributes
            p_PLL_CLKOUT_CFG    = 0x00,
            p_PLLx_CFG          = 0x01F03DC,
            p_PLLx_DMON_CFG     = 0b0,
            p_PLLx_FBDIV        = self.config["n2"],
            p_PLLx_FBDIV_45     = self.config["n1"],
            p_PLLx_INIT_CFG     = 0x00001E,
            p_PLLx_LOCK_CFG     = 0x1E8,
            p_PLLx_REFCLK_DIV   = self.config["m"],

            # Common Block - Dynamic Reconfiguration Port
            i_DRPCLK            = ClockSignal("ss"),
            i_DRPADDR           = self.drp.addr,
            i_DRPDI             = self.drp.di,
            o_DRPDO             = self.drp.do,
            i_DRPWE             = self.drp.we,
            i_DRPEN             = self.drp.en,
            o_DRPRDY            = self.drp.rdy,

            # Common Block - Clocking Ports
            i_GTREFCLK0         = self._refclk,
            o_PLLxOUTCLK        = self.clk,
            o_PLLxOUTREFCLK     = self.refclk,

            # Common Block - PLL Ports
            o_PLLxLOCK          = self.lock,
            i_PLLxLOCKEN        = 1,
            i_PLLxPD            = 0,
            i_PLLxREFCLKSEL     = 0b001,
            i_PLLxRESET         = self.reset,

            i_PLLyPD            = 1,

            # QPLL Ports
            i_BGBYPASSB         = 1,
            i_BGMONITORENB      = 1,
            i_BGPDB             = 1,
            i_BGRCALOVRD        = 0b11111,
            i_RCALENB           = 1,
        )

        if self.channel == 0:
            pll_x, pll_y = "PLL0", "PLL1"
        else:
            pll_x, pll_y = "PLL1", "PLL0"

        return Instance("GTPE2_COMMON", **{
            name.replace("PLLx", pll_x).replace("PLLy", pll_y): value
            for name, value in gtpe2_params.items()
        })


    @staticmethod
    def compute_config(refclk_freq, linerate):
        for n1 in 4, 5:
            for n2 in 1, 2, 3, 4, 5:
                for m in 1, 2:
                    vco_freq = refclk_freq*(n1*n2)/m
                    if 1.6e9 <= vco_freq <= 3.3e9:
                        for d in 1, 2, 4, 8, 16:
                            current_linerate = vco_freq*2/d
                            if current_linerate == linerate:
                                return {"n1": n1, "n2": n2, "m": m, "d": d,
                                        "vco_freq": vco_freq,
                                        "clkin": refclk_freq,
                                        "linerate": linerate}
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))

    def __repr__(self):
        config = self.config
        r = """
GTPQuadPLL
==========
  overview:
  ---------
       +--------------------------------------------------+
       |                                                  |
       |            +---------------------------+ +-----+ |
       |   +-----+  | Phase Frequency Detector  | |     | |
CLKIN +----> /M  +-->       Charge Pump         +-> VCO +---> CLKOUT
       |   +-----+  |       Loop Filter         | |     | |
       |            +---------------------------+ +--+--+ |
       |              ^                              |    |
       |              |    +-------+    +-------+    |    |
       |              +----+  /N2  <----+  /N1  <----+    |
       |                   +-------+    +-------+         |
       +--------------------------------------------------+
                            +-------+
                   CLKOUT +->  2/D  +-> LINERATE
                            +-------+
  config:
  -------
    CLKIN    = {clkin}MHz
    CLKOUT   = CLKIN x (N1 x N2) / M = {clkin}MHz x ({n1} x {n2}) / {m}
             = {vco_freq}GHz
    LINERATE = CLKOUT x 2 / D = {vco_freq}GHz x 2 / {d}
             = {linerate}GHz
""".format(clkin    = config["clkin"]/1e6,
           n1       = config["n1"],
           n2       = config["n2"],
           m        = config["m"],
           vco_freq = config["vco_freq"]/1e9,
           d        = config["d"],
           linerate = config["linerate"]/1e9)
        return r


class GTPChannel(Elaboratable):
    def __init__(self, qpll, tx_pads, rx_pads, ss_clock_frequency):
        self._qpll          = qpll
        self._tx_pads       = tx_pads
        self._rx_pads       = rx_pads
        self._ss_clock_frequency = ss_clock_frequency

        # For now, always operate at 2x gearing, and using the corresponding width for
        # the internal data path.
        self._io_words      = 2
        self._data_width    = self._io_words * 10

        #
        # I/O ports.
        #

        # Dynamic reconfiguration port
        self.drp            = DRPInterface()

        # Interface clock
        self.pclk           = Signal()

        # Reset sequencing
        self.reset          = Signal()
        self.tx_ready       = Signal()
        self.rx_ready       = Signal()

        # Core Rx and Tx lines
        self.tx_data        = Signal(self._io_words * 8)
        self.tx_datak       = Signal(self._io_words)
        self.rx_data        = Signal(self._io_words * 8)
        self.rx_datak       = Signal(self._io_words)

        # TX controls
        self.tx_polarity    = Signal()
        self.tx_elec_idle   = Signal()
        self.tx_gpio_en     = Signal()
        self.tx_gpio        = Signal()

        # RX controls
        self.rx_polarity    = Signal()
        self.rx_eq_training = Signal()
        self.rx_termination = Signal()

        # RX status
        self.rx_valid       = Signal()
        self.rx_status      = Signal(3)
        self.rx_elec_idle   = Signal()


    def elaborate(self, platform):
        m = Module()

        # Aliases.
        qpll       = self._qpll
        io_words   = self._io_words
        data_width = self._data_width

        #
        # Clocking.
        #

        # Ensure we have a valid PLL/CDR configuration.
        assert qpll.config["linerate"] < 6.6e9

        # From [UG482: Table 4-14]: CDR Recommended Settings for Protocols with SSC
        rxcdr_cfgs = {
            1: 0x0_0000_87FE_2060_2448_1010,
            2: 0x0_0000_47FE_2060_2450_1010,
            4: 0x0_0000_47FE_1060_2450_1010,
        }

        # Generate the PIPE interface clock from the transmit word clock, and use it to drive both
        # the Tx and the Rx FIFOs, to bring both halves of the data bus to the same clock domain.
        # The recovered Rx clock will not match the generated Tx clock; use the recovered word
        # clock to drive the CTC FIFO in the transceiver, which will compensate for the difference.
        txoutclk = Signal()
        m.submodules += Instance("BUFG",
            i_I=txoutclk,
            o_O=self.pclk
        )
        platform.add_clock_constraint(self.pclk, 250e6)

        # Transceiver uses a 25 MHz clock internally, which needs to be derived from
        # the reference clock.
        for clk25_div in range(1, 33):
            if qpll._refclk_freq / clk25_div <= 25e6:
                break

        # Out of band sequence detector uses an auxiliary clock whose frequency is derived
        # from the properties of the sequences.
        m.submodules.oob_clkdiv = oob_clkdiv = GTOOBClockDivider(self._ss_clock_frequency)


        #
        # Initialization.
        #

        # Per [AR43482], GTP transceivers must not be reset immediately after configuration.
        m.submodules.defer_rst = defer_rst = GTResetDeferrer(self._ss_clock_frequency)
        m.d.comb += [
            defer_rst.tx_i.eq(~qpll.lock | self.reset),
            defer_rst.rx_i.eq(~qpll.lock | self.reset),
        ]

        # Per [UG482], GTP receiver reset must follow a specific sequence.
        m.submodules.rx_pma_rst = rx_pma_rst = GTPRXPMAResetWorkaround(self._ss_clock_frequency)
        m.d.comb += [
            rx_pma_rst.i.eq(defer_rst.rx_o)
        ]

        tx_rst_done = Signal()
        rx_rst_done = Signal()
        m.d.comb += [
            self.tx_ready.eq(defer_rst.done & tx_rst_done),
            self.rx_ready.eq(defer_rst.done & rx_rst_done),
        ]


        #
        # Dynamic reconfiguration.
        #
        rx_termination = Signal()
        m.submodules += FFSynchronizer(self.rx_termination, rx_termination, o_domain="ss")

        m.submodules.rx_term = rx_term = DRPFieldController(
            addr=0x0011, bits=slice(4, 6), reset=0b10) # RX_CM_SEL
        m.d.comb += [
            rx_term.value.eq(Mux(rx_termination,
                                 0b11,    # Programmable
                                 0b10)),  # Floating
        ]

        m.submodules.drp_arbiter = drp_arbiter = DRPArbiter()
        drp_arbiter.add_interface(rx_pma_rst.drp)
        drp_arbiter.add_interface(rx_term.drp)
        drp_arbiter.add_interface(self.drp)


        #
        # Core SerDes instantiation.
        #
        m.submodules.gtp = Instance("GTPE2_CHANNEL",
            # Simulation-Only Attributes
            p_SIM_RECEIVER_DETECT_PASS   = "TRUE",
            p_SIM_TX_EIDLE_DRIVE_LEVEL   = "X",
            p_SIM_RESET_SPEEDUP          = "FALSE",
            p_SIM_VERSION                = "2.0",

            # RX 8B/10B Decoder Attributes
            p_RX_DISPERR_SEQ_MATCH       = "FALSE",
            p_DEC_MCOMMA_DETECT          = "TRUE",
            p_DEC_PCOMMA_DETECT          = "TRUE",
            p_DEC_VALID_COMMA_ONLY       = "TRUE",
            p_UCODEER_CLR                = 0b0,

            # RX Byte and Word Alignment Attributes
            p_ALIGN_COMMA_DOUBLE         = "FALSE",
            p_ALIGN_COMMA_ENABLE         = 0b1111_111111,
            p_ALIGN_COMMA_WORD           = 1,
            p_ALIGN_MCOMMA_DET           = "TRUE",
            p_ALIGN_MCOMMA_VALUE         = 0b0101_111100, # K28.5 RD- 10b code
            p_ALIGN_PCOMMA_DET           = "TRUE",
            p_ALIGN_PCOMMA_VALUE         = 0b1010_000011, # K28.5 RD+ 10b code
            p_SHOW_REALIGN_COMMA         = "TRUE",
            p_RXSLIDE_AUTO_WAIT          = 7,
            p_RXSLIDE_MODE               = "OFF",
            p_RX_SIG_VALID_DLY           = 10,

            # RX Clock Correction Attributes
            p_CBCC_DATA_SOURCE_SEL       = "DECODED",
            p_CLK_CORRECT_USE            = "TRUE",
            p_CLK_COR_KEEP_IDLE          = "FALSE",
            p_CLK_COR_MAX_LAT            = 14,
            p_CLK_COR_MIN_LAT            = 11,
            p_CLK_COR_PRECEDENCE         = "TRUE",
            p_CLK_COR_REPEAT_WAIT        = 0,
            p_CLK_COR_SEQ_LEN            = 2,
            p_CLK_COR_SEQ_1_ENABLE       = 0b1111,
            p_CLK_COR_SEQ_1_1            = 0b01_001_11100, # K28.1 1+8b code
            p_CLK_COR_SEQ_1_2            = 0b01_001_11100, # K28.1 1+8b code
            p_CLK_COR_SEQ_1_3            = 0b0000000000,
            p_CLK_COR_SEQ_1_4            = 0b0000000000,
            p_CLK_COR_SEQ_2_ENABLE       = 0b1111,
            p_CLK_COR_SEQ_2_USE          = "FALSE",
            p_CLK_COR_SEQ_2_1            = 0b0000000000,
            p_CLK_COR_SEQ_2_2            = 0b0000000000,
            p_CLK_COR_SEQ_2_3            = 0b0000000000,
            p_CLK_COR_SEQ_2_4            = 0b0000000000,

            # RX Channel Bonding Attributes
            p_CHAN_BOND_KEEP_ALIGN       = "FALSE",
            p_CHAN_BOND_MAX_SKEW         = 1,
            p_CHAN_BOND_SEQ_LEN          = 1,
            p_CHAN_BOND_SEQ_1_1          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_2          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_3          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_4          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_ENABLE     = 0b1111,
            p_CHAN_BOND_SEQ_2_1          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_2          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_3          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_4          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_ENABLE     = 0b1111,
            p_CHAN_BOND_SEQ_2_USE        = "FALSE",
            p_FTS_DESKEW_SEQ_ENABLE      = 0b1111,
            p_FTS_LANE_DESKEW_CFG        = 0b1111,
            p_FTS_LANE_DESKEW_EN         = "FALSE",

            # RX Margin Analysis Attributes
            p_ES_CONTROL                 = 0b000000,
            p_ES_ERRDET_EN               = "FALSE",
            p_ES_EYE_SCAN_EN             = "TRUE",
            p_ES_HORZ_OFFSET             = 0x000,
            p_ES_PMA_CFG                 = 0b0000000000,
            p_ES_PRESCALE                = 0b00000,
            p_ES_QUALIFIER               = 0x00000000000000000000,
            p_ES_QUAL_MASK               = 0x00000000000000000000,
            p_ES_SDATA_MASK              = 0x00000000000000000000,
            p_ES_VERT_OFFSET             = 0b000000000,

            # FPGA RX Interface Attributes
            p_RX_DATA_WIDTH              = data_width,

            # PMA Attributes
            p_OUTREFCLK_SEL_INV          = 0b11,
            p_PMA_RSV                    = 0x00000333,
            p_PMA_RSV2                   = 0x00002040,
            p_PMA_RSV3                   = 0b00,
            p_PMA_RSV4                   = 0b0000,
            p_RX_BIAS_CFG                = 0b0000111100110011,
            p_DMONITOR_CFG               = 0x000A00,
            p_RX_CM_SEL                  = 0b10,
            p_RX_CM_TRIM                 = 0b1010,
            p_RX_DEBUG_CFG               = 0b00000000000000,
            p_RX_OS_CFG                  = 0b0000010000000,
            p_TERM_RCAL_CFG              = 0b100001000010000,
            p_TERM_RCAL_OVRD             = 0b000,
            p_TST_RSV                    = 0x00000000,
            p_RX_CLK25_DIV               = clk25_div,
            p_TX_CLK25_DIV               = clk25_div,

            # PCI Express Attributes
            p_PCS_PCIE_EN                = "FALSE",

            # PCS Attributes
            p_PCS_RSVD_ATTR              = 0x0000_0000_0100, # OOB power up

            # RX Buffer Attributes
            p_RXBUF_ADDR_MODE            = "FULL",
            p_RXBUF_EIDLE_HI_CNT         = 0b1000,
            p_RXBUF_EIDLE_LO_CNT         = 0b0000,
            p_RXBUF_EN                   = "TRUE",
            p_RX_BUFFER_CFG              = 0b000000,
            p_RXBUF_RESET_ON_CB_CHANGE   = "TRUE",
            p_RXBUF_RESET_ON_COMMAALIGN  = "FALSE",
            p_RXBUF_RESET_ON_EIDLE       = "FALSE",
            p_RXBUF_RESET_ON_RATE_CHANGE = "TRUE",
            p_RXBUFRESET_TIME            = 0b00001,
            p_RXBUF_THRESH_OVFLW         = 61,
            p_RXBUF_THRESH_OVRD          = "FALSE",
            p_RXBUF_THRESH_UNDFLW        = 4,
            p_RXDLY_CFG                  = 0x001F,
            p_RXDLY_LCFG                 = 0x030,
            p_RXDLY_TAP_CFG              = 0x0000,
            p_RXPH_CFG                   = 0xC00002,
            p_RXPHDLY_CFG                = 0x084020,
            p_RXPH_MONITOR_SEL           = 0b00000,
            p_RX_XCLK_SEL                = "RXREC",
            p_RX_DDI_SEL                 = 0b000000,
            p_RX_DEFER_RESET_BUF_EN      = "TRUE",

            # CDR Attributes
            p_RXCDR_CFG                  = rxcdr_cfgs[qpll.config["d"]],
            p_RXCDR_FR_RESET_ON_EIDLE    = 0b0,
            p_RXCDR_HOLD_DURING_EIDLE    = 0b0,
            p_RXCDR_PH_RESET_ON_EIDLE    = 0b0,
            p_RXCDR_LOCK_CFG             = 0b001001,

            # RX Initialization and Reset Attributes
            p_RXCDRFREQRESET_TIME        = 0b00001,
            p_RXCDRPHRESET_TIME          = 0b00001,
            p_RXISCANRESET_TIME          = 0b00001,
            p_RXPCSRESET_TIME            = 0b00001,
            p_RXPMARESET_TIME            = 0b00011,

            # RX OOB Signaling Attributes
            p_RXOOB_CFG                  = 0b0000110,

            # RX Gearbox Attributes
            p_RXGEARBOX_EN               = "FALSE",
            p_GEARBOX_MODE               = 0b000,

            # PRBS Detection Attribute
            p_RXPRBS_ERR_LOOPBACK        = 0b0,

            # Power-Down Attributes
            p_PD_TRANS_TIME_FROM_P2      = 0x03c,
            p_PD_TRANS_TIME_NONE_P2      = 0x3c,
            p_PD_TRANS_TIME_TO_P2        = 0x64,

            # RX OOB Signaling Attributes
            p_SAS_MAX_COM                = 64,
            p_SAS_MIN_COM                = 36,
            p_SATA_BURST_SEQ_LEN         = 0b0101,
            p_SATA_BURST_VAL             = 0b100,
            p_SATA_EIDLE_VAL             = 0b100,
            p_SATA_MAX_BURST             = 8,
            p_SATA_MAX_INIT              = 21,
            p_SATA_MAX_WAKE              = 7,
            p_SATA_MIN_BURST             = 4,
            p_SATA_MIN_INIT              = 12,
            p_SATA_MIN_WAKE              = 4,

            # RX Fabric Clock Output Control Attributes
            p_TRANS_TIME_RATE            = 0x0E,

            # TX Buffer Attributes
            p_TXBUF_EN                   = "TRUE",
            p_TXBUF_RESET_ON_RATE_CHANGE = "TRUE",
            p_TXDLY_CFG                  = 0x001F,
            p_TXDLY_LCFG                 = 0x030,
            p_TXDLY_TAP_CFG              = 0x0000,
            p_TXPH_CFG                   = 0x0780,
            p_TXPHDLY_CFG                = 0x084020,
            p_TXPH_MONITOR_SEL           = 0b00000,
            p_TX_XCLK_SEL                = "TXOUT",

            # FPGA TX Interface Attributes
            p_TX_DATA_WIDTH              = data_width,

            # TX Configurable Driver Attributes
            p_TX_DEEMPH0                 = 0b000000,
            p_TX_DEEMPH1                 = 0b000000,
            p_TX_DRIVE_MODE              = "DIRECT",
            p_TX_EIDLE_ASSERT_DELAY      = 0b110,
            p_TX_EIDLE_DEASSERT_DELAY    = 0b100,
            p_TX_LOOPBACK_DRIVE_HIZ      = "FALSE",
            p_TX_MAINCURSOR_SEL          = 0b0,
            p_TX_MARGIN_FULL_0           = 0b1001110,
            p_TX_MARGIN_FULL_1           = 0b1001001,
            p_TX_MARGIN_FULL_2           = 0b1000101,
            p_TX_MARGIN_FULL_3           = 0b1000010,
            p_TX_MARGIN_FULL_4           = 0b1000000,
            p_TX_MARGIN_LOW_0            = 0b1000110,
            p_TX_MARGIN_LOW_1            = 0b1000100,
            p_TX_MARGIN_LOW_2            = 0b1000010,
            p_TX_MARGIN_LOW_3            = 0b1000000,
            p_TX_MARGIN_LOW_4            = 0b1000000,
            p_TX_PREDRIVER_MODE          = 0b0,
            p_PMA_RSV5                   = 0b0,

            # TX Gearbox Attributes
            p_TXGEARBOX_EN               = "FALSE",

            # TX Initialization and Reset Attributes
            p_TXPCSRESET_TIME            = 0b00001,
            p_TXPMARESET_TIME            = 0b00001,

            # TX Receiver Detection Attributes
            p_TX_RXDETECT_CFG            = 0x1832,
            p_TX_RXDETECT_REF            = 0b100,

            # JTAG Attributes
            p_ACJTAG_DEBUG_MODE          = 0b0,
            p_ACJTAG_MODE                = 0b0,
            p_ACJTAG_RESET               = 0b0,

            # CDR Attributes
            p_CFOK_CFG                   = 0x49000040E80,
            p_CFOK_CFG2                  = 0b0100000,
            p_CFOK_CFG3                  = 0b0100000,
            p_CFOK_CFG4                  = 0b0,
            p_CFOK_CFG5                  = 0x0,
            p_CFOK_CFG6                  = 0b0000,
            p_RXOSCALRESET_TIME          = 0b00011,
            p_RXOSCALRESET_TIMEOUT       = 0b00000,

            # PMA Attributes
            p_CLK_COMMON_SWING           = 0b0,
            p_RX_CLKMUX_EN               = 0b1,
            p_TX_CLKMUX_EN               = 0b1,
            p_ES_CLK_PHASE_SEL           = 0b0,
            p_USE_PCS_CLK_PHASE_SEL      = 0b0,
            p_PMA_RSV6                   = 0b0,
            p_PMA_RSV7                   = 0b0,

            # RX Fabric Clock Output Control Attributes
            p_RXOUT_DIV                  = qpll.config["d"],

            # TX Fabric Clock Output Control Attributes
            p_TXOUT_DIV                  = qpll.config["d"],

            # RX Phase Interpolator Attributes
            p_RXPI_CFG0                  = 0b000,
            p_RXPI_CFG1                  = 0b1,
            p_RXPI_CFG2                  = 0b1,

            # RX Equalizer Attributes
            p_ADAPT_CFG0                 = 0x00000,
            p_RXLPMRESET_TIME            = 0b0001111,
            p_RXLPM_BIAS_STARTUP_DISABLE = 0b0,
            p_RXLPM_CFG                  = 0b0110,
            p_RXLPM_CFG1                 = 0b0,
            p_RXLPM_CM_CFG               = 0b0,
            p_RXLPM_GC_CFG               = 0b111100010,
            p_RXLPM_GC_CFG2              = 0b001,
            p_RXLPM_HF_CFG               = 0b00001111110000,
            p_RXLPM_HF_CFG2              = 0b01010,
            p_RXLPM_HF_CFG3              = 0b0000,
            p_RXLPM_HOLD_DURING_EIDLE    = 0b0,
            p_RXLPM_INCM_CFG             = 0b1,
            p_RXLPM_IPCM_CFG             = 0b0,
            p_RXLPM_LF_CFG               = 0b000000001111110000,
            p_RXLPM_LF_CFG2              = 0b01010,
            p_RXLPM_OSINT_CFG            = 0b100,

            # TX Phase Interpolator PPM Controller Attributes
            p_TXPI_CFG0                  = 0b00,
            p_TXPI_CFG1                  = 0b00,
            p_TXPI_CFG2                  = 0b00,
            p_TXPI_CFG3                  = 0b0,
            p_TXPI_CFG4                  = 0b0,
            p_TXPI_CFG5                  = 0b000,
            p_TXPI_GREY_SEL              = 0b0,
            p_TXPI_INVSTROBE_SEL         = 0b0,
            p_TXPI_PPMCLK_SEL            = "TXUSRCLK2",
            p_TXPI_PPM_CFG               = 0x00,
            p_TXPI_SYNFREQ_PPM           = 0b001,

            # LOOPBACK Attributes
            p_LOOPBACK_CFG               = 0b0,
            p_PMA_LOOPBACK_CFG           = 0b0,

            # RX OOB Signalling Attributes
            p_RXOOB_CLK_CFG              = "FABRIC",

            # TX OOB Signalling Attributes
            p_SATA_PLL_CFG               = "VCO_3000MHZ",
            p_TXOOB_CFG                  = 0b0,

            # RX Buffer Attributes
            p_RXSYNC_MULTILANE           = 0b0,
            p_RXSYNC_OVRD                = 0b0,
            p_RXSYNC_SKIP_DA             = 0b0,

            # TX Buffer Attributes
            p_TXSYNC_MULTILANE           = 0b0,
            p_TXSYNC_OVRD                = 0b0,
            p_TXSYNC_SKIP_DA             = 0b0,

            # CPLL Ports
            i_GTRSVD                = 0b0000000000000000,
            i_PCSRSVDIN             = 0b0000000000000000,
            i_TSTIN                 = 0b11111111111111111111,

            # Channel - DRP Ports
            i_DRPCLK                = ClockSignal("ss"),
            i_DRPADDR               = drp_arbiter.shared.addr,
            i_DRPDI                 = drp_arbiter.shared.di,
            o_DRPDO                 = drp_arbiter.shared.do,
            i_DRPWE                 = drp_arbiter.shared.we,
            i_DRPEN                 = drp_arbiter.shared.en,
            o_DRPRDY                = drp_arbiter.shared.rdy,

            # Transceiver Reset Mode Operation
            i_GTRESETSEL            = 0,
            i_RESETOVRD             = 0,

            # Clocking Ports
            i_PLL0CLK               = qpll.clk    if qpll.channel == 0 else 0,
            i_PLL0REFCLK            = qpll.refclk if qpll.channel == 0 else 0,
            i_PLL1CLK               = qpll.clk    if qpll.channel == 1 else 0,
            i_PLL1REFCLK            = qpll.refclk if qpll.channel == 1 else 0,
            i_RXSYSCLKSEL           =        0b00 if qpll.channel == 0 else 0b11,
            i_TXSYSCLKSEL           =        0b00 if qpll.channel == 0 else 0b11,

            # Loopback Ports
            i_LOOPBACK              = 0b000,

            # PMA Reserved Ports
            i_PMARSVDIN3            = 0b0,
            i_PMARSVDIN4            = 0b0,

            # Power-Down Ports
            i_RXPD                  = 0,
            i_TXPD                  = 0b00,

            # RX Initialization and Reset Ports
            i_EYESCANRESET          = 0,
            i_GTRXRESET             = rx_pma_rst.o,
            i_RXLPMRESET            = 0,
            i_RXOOBRESET            = 0,
            i_RXPCSRESET            = 0,
            i_RXPMARESET            = 0,
            o_RXPMARESETDONE        = rx_pma_rst.rxpmaresetdone,
            o_RXRESETDONE           = rx_rst_done,
            i_RXUSERRDY             = 1,

            # Receive Ports
            i_CLKRSVD0              = 0,
            i_CLKRSVD1              = 0,
            i_DMONFIFORESET         = 0,
            i_DMONITORCLK           = 0,
            i_SIGVALIDCLK           = oob_clkdiv.o,

            # Receive Ports - CDR Ports
            i_RXCDRFREQRESET        = 0,
            i_RXCDRHOLD             = 0,
            o_RXCDRLOCK             = Open(),
            i_RXCDROVRDEN           = 0,
            i_RXCDRRESET            = 0,
            i_RXCDRRESETRSV         = 0,
            i_RXOSCALRESET          = 0,
            i_RXOSINTCFG            = 0b0010,
            o_RXOSINTDONE           = Open(),
            i_RXOSINTHOLD           = 0,
            i_RXOSINTOVRDEN         = 0,
            i_RXOSINTPD             = 0,
            o_RXOSINTSTARTED        = Open(),
            i_RXOSINTSTROBE         = 0,
            o_RXOSINTSTROBESTARTED  = Open(),
            i_RXOSINTTESTOVRDEN     = 0,

            # Receive Ports - Clock Correction Ports
            o_RXCLKCORCNT           = Open(2),

            # Receive Ports - FPGA RX Interface Datapath Configuration
            i_RX8B10BEN             = 1,

            # Receive Ports - FPGA RX Interface Ports
            o_RXDATA                = self.rx_data,
            i_RXUSRCLK              = self.pclk,
            i_RXUSRCLK2             = self.pclk,

            # Receive Ports - Pattern Checker Ports
            o_RXPRBSERR             = Open(),
            i_RXPRBSSEL             = 0b000,
            i_RXPRBSCNTRESET        = 0,

            # Receive Ports - PCI Express Ports
            o_PHYSTATUS             = Open(),
            i_RXRATE                = 0,
            o_RXSTATUS              = self.rx_status,
            o_RXVALID               = self.rx_valid,

            # Receive Ports - RX 8B/10B Decoder Ports
            o_RXCHARISCOMMA         = Open(4),
            o_RXCHARISK             = self.rx_datak,
            o_RXDISPERR             = Open(4),
            o_RXNOTINTABLE          = Open(4),
            i_SETERRSTATUS          = 0,

            # Receive Ports - RX AFE Ports
            i_GTPRXN                = self._rx_pads.n,
            i_GTPRXP                = self._rx_pads.p,
            i_PMARSVDIN2            = 0b0,
            o_PMARSVDOUT0           = Open(),
            o_PMARSVDOUT1           = Open(),

            # Receive Ports - RX Buffer Bypass Ports
            i_RXBUFRESET            = 0,
            o_RXBUFSTATUS           = Open(3),
            i_RXDDIEN               = 0,
            i_RXDLYBYPASS           = 1,
            i_RXDLYEN               = 0,
            i_RXDLYOVRDEN           = 0,
            i_RXDLYSRESET           = 0,
            o_RXDLYSRESETDONE       = Open(),
            i_RXPHALIGN             = 0,
            o_RXPHALIGNDONE         = Open(),
            i_RXPHALIGNEN           = 0,
            i_RXPHDLYPD             = 0,
            i_RXPHDLYRESET          = 0,
            o_RXPHMONITOR           = Open(5),
            i_RXPHOVRDEN            = 0,
            o_RXPHSLIPMONITOR       = Open(5),
            i_RXSYNCALLIN           = 0,
            o_RXSYNCDONE            = Open(),
            i_RXSYNCIN              = 0,
            i_RXSYNCMODE            = 0,
            o_RXSYNCOUT             = Open(),

            # Receive Ports - RX Byte and Word Alignment Ports
            o_RXBYTEISALIGNED       = Open(),
            o_RXBYTEREALIGN         = Open(),
            o_RXCOMMADET            = Open(),
            i_RXCOMMADETEN          = 1,
            i_RXMCOMMAALIGNEN       = 1,
            i_RXPCOMMAALIGNEN       = 1,
            i_RXSLIDE               = 0,

            # Receive Ports - RX Channel Bonding Ports
            o_RXCHANBONDSEQ         = Open(),
            o_RXCHANISALIGNED       = Open(),
            o_RXCHANREALIGN         = Open(),
            i_RXCHBONDEN            = 0,
            i_RXCHBONDI             = 0b0000,
            i_RXCHBONDLEVEL         = 0b000,
            i_RXCHBONDMASTER        = 0,
            o_RXCHBONDO             = Open(4),
            i_RXCHBONDSLAVE         = 0,

            # Receive Ports - RX Decision Feedback Equalizer
            o_DMONITOROUT           = Open(15),
            i_RXADAPTSELTEST        = 0,
            i_RXDFEXYDEN            = 0,
            i_RXOSINTEN             = 0b1,
            i_RXOSINTID0            = 0,
            i_RXOSINTNTRLEN         = 0,
            o_RXOSINTSTROBEDONE     = Open(),

            # Receive Ports - RX Equalizer Ports
            i_RXLPMHFHOLD           = ~self.rx_eq_training,
            i_RXLPMHFOVRDEN         = 0,
            i_RXLPMLFHOLD           = ~self.rx_eq_training,
            i_RXLPMLFOVRDEN         = 0,
            i_RXLPMOSINTNTRLEN      = 0,
            i_RXOSHOLD              = ~self.rx_eq_training,
            i_RXOSOVRDEN            = 0,

            # Receive Ports - RX Fabric Clock Output Control Ports
            o_RXRATEDONE            = Open(),
            i_RXRATEMODE            = 0b0,

            # Receive Ports - RX Fabric Output Control Ports
            o_RXOUTCLK              = Open(),
            o_RXOUTCLKFABRIC        = Open(),
            o_RXOUTCLKPCS           = Open(),
            i_RXOUTCLKSEL           = 0b010,

            # Receive Ports - RX Gearbox Ports
            o_RXDATAVALID           = Open(2),
            o_RXHEADER              = Open(3),
            o_RXHEADERVALID         = Open(),
            o_RXSTARTOFSEQ          = Open(2),
            i_RXGEARBOXSLIP         = 0,

            # Receive Ports - RX Margin Analysis Ports
            o_EYESCANDATAERROR      = Open(),
            i_EYESCANMODE           = 0,
            i_EYESCANTRIGGER        = 0,

            # Receive Ports - RX OOB Signaling Ports
            o_RXCOMSASDET           = Open(),
            o_RXCOMWAKEDET          = Open(),
            o_RXCOMINITDET          = Open(),
            o_RXELECIDLE            = self.rx_elec_idle,
            i_RXELECIDLEMODE        = 0b00,

            # Receive Ports - RX Polarity Control Ports
            i_RXPOLARITY            = self.rx_polarity,

            # TX Initialization and Reset Ports
            i_CFGRESET              = 0,
            i_GTTXRESET             = defer_rst.tx_o,
            i_TXPCSRESET            = 0,
            i_TXPMARESET            = 0,
            o_TXPMARESETDONE        = Open(),
            o_TXRESETDONE           = tx_rst_done,
            i_TXUSERRDY             = 1,
            o_PCSRSVDOUT            = Open(),

            # Transmit Ports - Configurable Driver Ports
            o_GTPTXN                = self._tx_pads.n,
            o_GTPTXP                = self._tx_pads.p,
            i_TXBUFDIFFCTRL         = 0b100,
            i_TXDEEMPH              = 0,
            i_TXDIFFCTRL            = 0b1000,
            i_TXDIFFPD              = 0,
            i_TXINHIBIT             = self.tx_gpio_en,
            i_TXMAINCURSOR          = 0b0000000,
            i_TXPISOPD              = 0,
            i_TXPOSTCURSOR          = 0b00000,
            i_TXPOSTCURSORINV       = 0,
            i_TXPRECURSOR           = 0b00000,
            i_TXPRECURSORINV        = 0,
            i_PMARSVDIN0            = 0b0,
            i_PMARSVDIN1            = 0b0,

            # Transmit Ports - FPGA TX Interface Datapath Configuration
            i_TX8B10BEN             = 1,

            # Transmit Ports - FPGA TX Interface Ports
            i_TXUSRCLK              = self.pclk,
            i_TXUSRCLK2             = self.pclk,

            # Transmit Ports - PCI Express Ports
            i_TXELECIDLE            = ~self.tx_gpio_en & self.tx_elec_idle,
            i_TXMARGIN              = 0,
            i_TXRATE                = 0b000,
            i_TXSWING               = 0,

            # Transmit Ports - Pattern Generator Ports
            i_TXPRBSSEL             = 0b000,
            i_TXPRBSFORCEERR        = 0,

            # Transmit Ports - TX 8B/10B Encoder Ports
            i_TX8B10BBYPASS         = 0b0000,
            i_TXCHARDISPMODE        = 0b0000,
            i_TXCHARDISPVAL         = 0b0000,
            i_TXCHARISK             = self.tx_datak,

            # Transmit Ports - TX Data Path Interface
            i_TXDATA                = self.tx_data,

            # Transmit Ports - TX Buffer Bypass Ports
            i_TXDLYBYPASS           = 1,
            i_TXDLYEN               = 0,
            i_TXDLYHOLD             = 0,
            i_TXDLYOVRDEN           = 0,
            i_TXDLYSRESET           = 0,
            o_TXDLYSRESETDONE       = Open(),
            i_TXDLYUPDOWN           = 0,
            i_TXPHALIGN             = 0,
            o_TXPHALIGNDONE         = Open(),
            i_TXPHALIGNEN           = 0,
            i_TXPHDLYPD             = 0,
            i_TXPHDLYRESET          = 0,
            i_TXPHDLYTSTCLK         = 0,
            i_TXPHINIT              = 0,
            o_TXPHINITDONE          = Open(),
            i_TXPHOVRDEN            = 0,

            # Transmit Ports - TX Buffer Ports
            o_TXBUFSTATUS           = Open(2),

            # Transmit Ports - TX Buffer and Phase Alignment Ports
            i_TXSYNCALLIN           = 0,
            o_TXSYNCDONE            = Open(),
            i_TXSYNCIN              = 0,
            i_TXSYNCMODE            = 0,
            o_TXSYNCOUT             = Open(),

            # Transmit Ports - TX Fabric Clock Output Control Ports
            o_TXOUTCLK              = txoutclk,
            o_TXOUTCLKFABRIC        = Open(),
            o_TXOUTCLKPCS           = Open(),
            i_TXOUTCLKSEL           = 0b010,
            i_TXRATEMODE            = 0,
            o_TXRATEDONE            = Open(),

            # Transmit Ports - TX Gearbox Ports
            o_TXGEARBOXREADY        = Open(),
            i_TXHEADER              = 0b000,
            i_TXSEQUENCE            = 0b0000000,
            i_TXSTARTSEQ            = 0,

            # Transmit Ports - TX OOB Signalling Ports
            o_TXCOMFINISH           = Open(),
            i_TXCOMINIT             = 0,
            i_TXCOMSAS              = 0,
            i_TXCOMWAKE             = 0,
            i_TXPDELECIDLEMODE      = 0,

            # Transmit Ports - TX Phase Interpolator PPM Controller Ports
            i_TXPIPPMEN             = 0,
            i_TXPIPPMOVRDEN         = 0,
            i_TXPIPPMPD             = 0,
            i_TXPIPPMSEL            = 1,
            i_TXPIPPMSTEPSIZE       = 0,

            # Transmit Ports - TX Polarity Control Ports
            i_TXPOLARITY            = self.tx_polarity ^ (self.tx_gpio_en & self.tx_gpio),

            # Transmit Ports - TX Receiver Detection Ports
            i_TXDETECTRX            = 0,
        )

        return m



class XC7GTPSerDesPIPE(PIPEInterface, Elaboratable):
    """ Wrapper around the core GTP SerDes that adapts it to the PIPE interface.

    The implementation-dependent behavior of the standard PIPE signals is described below:

    width :
        Interface width. Always 2 symbols.
    clk :
        Reference clock for the PHY receiver and transmitter. Could be routed through fabric,
        or connected to the output of an ``IBUFDS_GTE2`` block.
    pclk :
        Clock for the PHY interface. Frequency is always 250 MHz.
    phy_mode :
        PHY operating mode. Only SuperSpeed USB mode is supported.
    elas_buf_mode :
        Elastic buffer mode. Only nominal half-full mode is supported.
    rate :
        Link signaling rate. Only 5 GT/s is supported.
    power_down :
        Power management mode. Only P0 is supported.
    tx_deemph :
        Transmitter de-emphasis level. Only TBD is supported.
    tx_margin :
        Transmitter voltage levels. Only TBD is supported.
    tx_swing :
        Transmitter voltage swing level. Only full swing is supported.
    tx_detrx_lpbk :
    tx_elec_idle :
        Transmit control signals. Loopback and receiver detection are not implemented.
    tx_compliance :
    tx_ones_zeroes :
        These inputs are not implemented.
    power_present :
        This output is not implemented. External logic may drive it if necessary.
    """
    def __init__(self, *, tx_pads, rx_pads, refclk_frequency, ss_clock_frequency):
        super().__init__(width=2)

        self._tx_pads            = tx_pads
        self._rx_pads            = rx_pads
        self._refclk_frequency   = refclk_frequency
        self._ss_clock_frequency = ss_clock_frequency


    def elaborate(self, platform):
        m = Module()

        #
        # PLL and SerDes instantiation.
        #
        m.submodules.qpll = qpll = GTPQuadPLL(
            refclk              = self.clk,
            refclk_freq         = self._refclk_frequency,
            linerate            = 5e9
        )
        m.submodules.serdes = serdes = GTPChannel(
            qpll                = qpll,
            tx_pads             = self._tx_pads,
            rx_pads             = self._rx_pads,
            ss_clock_frequency  = self._ss_clock_frequency
        )

        # Our soft PHY includes some logic that needs to run synchronously to the PIPE clock; create
        # a local clock domain to drive it.
        m.domains.pipe = ClockDomain(local=True, async_reset=True)
        m.d.comb += [
            ClockSignal("pipe")     .eq(serdes.pclk),
        ]


        #
        # LFPS generation.
        #
        m.submodules.lfps_generator = lfps_generator = LFPSSquareWaveGenerator(25e6, 250e6)
        m.d.comb += [
            serdes.tx_gpio_en       .eq(lfps_generator.tx_gpio_en),
            serdes.tx_gpio          .eq(lfps_generator.tx_gpio),
        ]


        #
        # PIPE interface signaling.
        #
        m.d.comb += [
            qpll.reset              .eq(self.reset),
            serdes.reset            .eq(self.reset),
            self.pclk               .eq(serdes.pclk),

            serdes.tx_elec_idle     .eq(self.tx_elec_idle),
            serdes.rx_polarity      .eq(self.rx_polarity),
            serdes.rx_eq_training   .eq(self.rx_eq_training),
            serdes.rx_termination   .eq(self.rx_termination),
            lfps_generator.generate .eq(self.tx_detrx_lpbk & self.tx_elec_idle),

            self.phy_status         .eq(~serdes.tx_ready),
            self.rx_valid           .eq(serdes.rx_valid),
            self.rx_status          .eq(serdes.rx_status),
            self.rx_elec_idle       .eq(serdes.rx_elec_idle),

            serdes.tx_data          .eq(self.tx_data),
            serdes.tx_datak         .eq(self.tx_datak),
            self.rx_data            .eq(serdes.rx_data),
            self.rx_datak           .eq(serdes.rx_datak),
        ]

        return m
