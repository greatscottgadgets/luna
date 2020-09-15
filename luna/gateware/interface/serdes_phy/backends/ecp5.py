#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2020 whitequark@whitequark.org
#
# The ECP5's DCU parameters/signals/instance have been partially documented by whitequark
# as part of the Yumewatari project: https://github.com/whitequark/Yumewatari.
#
# Code based in part on ``litex`` and ``liteiclink``.
# SPDX-License-Identifier: BSD-3-Clause

from nmigen import *
from nmigen.lib.cdc import FFSynchronizer, ResetSynchronizer

from ....usb.stream import USBRawSuperSpeedStream
from ..serdes       import TxDatapath, RxDatapath


class ECP5SerDesPLLConfiguration:
    def __init__(self, refclk, refclk_freq, linerate):
        self.refclk = refclk
        self.config = self.compute_config(refclk_freq, linerate)

    @staticmethod
    def compute_config(refclk_freq, linerate):
        for mult in [8, 10, 16, 20, 25]:
            current_linerate = refclk_freq*mult
            if current_linerate == linerate:
                return {
                    "mult":       mult,
                    "refck_freq": refclk_freq,
                    "linerate":   linerate,
                }
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))



class ECP5SerDesConfigInterface(Elaboratable):
    """ Module that interfaces with the ECP5's SerDes Client Interface (SCI). """

    def __init__(self, serdes):
        self._serdes = serdes

        #
        # I/O port
        #

        # Control interface.
        self.dual_sel = Signal()
        self.chan_sel = Signal()
        self.re       = Signal()
        self.we       = Signal()
        self.done     = Signal()
        self.adr      = Signal(6)
        self.dat_w    = Signal(8)
        self.dat_r    = Signal(8)

        # SCI interface.
        self.sci_rd    = Signal()
        self.sci_wrn   = Signal()
        self.sci_addr  = Signal(6)
        self.sci_wdata = Signal(8)
        self.sci_rdata = Signal(8)



    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.sci_wrn.eq(1),

            self.sci_addr.eq(self.adr),
            self.sci_wdata.eq(self.dat_w)
        ]

        with m.FSM(domain="ss"):

            with m.State("IDLE"):
                m.d.comb += self.done.eq(1)

                with m.If(self.we):
                    m.next = "WRITE"
                with m.Elif(self.re):
                    m.d.comb += self.sci_rd.eq(1),
                    m.next = "READ"

            with m.State("WRITE"):
                m.d.comb += self.sci_wrn.eq(0)
                m.next = "IDLE"


            with m.State("READ"):
                m.d.comb += self.sci_rd.eq(1)
                m.d.ss   += self.dat_r.eq(self.sci_rdata)
                m.next = "IDLE"

        return m


class ECP5SerDesRegisterTranslator(Elaboratable):
    """ Interface that converts control signals into SerDes register reads and writes. """

    def __init__(self, serdes, sci):
        self._serdes = serdes
        self._sci    = sci

        #
        # I/O port
        #
        self.loopback    = Signal()
        self.rx_polarity = Signal()
        self.tx_idle     = Signal()
        self.tx_polarity = Signal()


    def elaborate(self, platform):
        m = Module()
        sci = self._sci

        first = Signal()
        data  = Signal(8)


        with m.FSM(domain="ss"):

            with m.State("IDLE"):
                m.d.ss += first.eq(1)
                m.next = "READ-CH_01"

            with m.State("READ-CH_01"):
                m.d.ss += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.re.eq(1),
                    sci.adr.eq(0x01),
                ]

                with m.If(~first & sci.done):
                    m.d.comb += sci.re.eq(0)
                    m.d.ss += [
                        data.eq(sci.dat_r),
                        first.eq(1)
                    ]
                    m.next = "WRITE-CH_01"


            with m.State("WRITE-CH_01"):
                m.d.ss += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.we.eq(1),
                    sci.adr.eq(0x01),
                    sci.dat_w.eq(data),
                    sci.dat_w[0].eq(self.rx_polarity),
                    sci.dat_w[1].eq(self.tx_polarity),
                ]
                with m.If(~first & sci.done):
                    m.d.comb += sci.we.eq(0)
                    m.d.ss   += first.eq(1)
                    m.next = "READ-CH_02"

            with m.State("READ-CH_02"):
                m.d.ss   += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.re.eq(1),
                    sci.adr.eq(0x02),
                ]

                with m.If(~first & sci.done):
                    m.d.comb += sci.re.eq(0)
                    m.d.ss   += data.eq(sci.dat_r)
                    m.next = "WRITE-CH_02"

            with m.State("WRITE-CH_02"):
                m.d.ss   += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.we.eq(1),
                    sci.adr.eq(0x02),
                    sci.dat_w.eq(data),
                    sci.dat_w[6].eq(self.tx_idle),  # pcie_ei_en
                ]

                with m.If(~first & sci.done):
                    m.d.ss   += first.eq(1)
                    m.d.comb += sci.we.eq(0)
                    m.next = "READ-CH_15"

            with m.State("READ-CH_15"):
                m.d.ss   += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.re.eq(1),
                    sci.adr.eq(0x15),
                ]

                with m.If(~first & sci.done):
                    m.d.ss   += first.eq(1)
                    m.d.comb += sci.re.eq(0)
                    m.d.ss += data.eq(sci.dat_r)
                    m.next = "WRITE-CH_15"

            with m.State("WRITE-CH_15"):
                m.d.ss   += first.eq(0)
                m.d.comb += [
                    sci.chan_sel.eq(1),
                    sci.we.eq(1),
                    sci.adr.eq(0x15),
                    sci.dat_w.eq(data),
                ]
                with m.If(self.loopback):
                    m.d.comb += sci.dat_w[0:4].eq(0b0001) # lb_ctl

                with m.If(~first & sci.done):
                    m.d.comb += sci.we.eq(0)
                    m.next = "IDLE"

        return m


class ECP5SerDes(Elaboratable):
    """ Abstraction layer for working with the ECP5 SerDes. """

    def __init__(self, pll_config, tx_pads, rx_pads, dual=0, channel=0):
        assert dual    in [0, 1]
        assert channel in [0, 1]

        self._pll                   = pll_config
        self._tx_pads               = tx_pads
        self._rx_pads               = rx_pads
        self._dual                  = dual
        self._channel               = channel

        # For now, we'll always operate with 2x gearing -- which means that we internally are working
        # with 20 bits of 8b10b encoded data.
        self._io_words      = 2
        self._io_data_width = 8 * self._io_words

        #
        # I/O port.
        #

        # Core Rx and Tx lines.

        self.sink   = USBRawSuperSpeedStream(payload_words=self._io_words)
        self.source = USBRawSuperSpeedStream(payload_words=self._io_words)

        # TX controls
        self.tx_enable              = Signal(reset=1)
        self.tx_ready               = Signal()
        self.tx_inhibit             = Signal() # FIXME
        self.tx_produce_square_wave = Signal()
        self.tx_produce_pattern     = Signal()
        self.tx_pattern             = Signal(20)
        self.tx_idle                = Signal()
        self.tx_invert              = Signal()
        self.tx_gpio_en             = Signal()
        self.tx_gpio                = Signal()

        # RX controls
        self.rx_enable              = Signal(reset=1)
        self.rx_ready               = Signal()
        self.rx_align               = Signal(reset=1)
        self.rx_idle                = Signal()
        self.rx_invert              = Signal()
        self.rx_gpio                = Signal()

        # Loopback
        self.loopback               = Signal() # FIXME: reconfigure lb_ctl to 0b0001 but does not seem enough


    def elaborate(self, platform):
        m = Module()

        # The ECP5 SerDes uses a simple feedback mechanism to keep its FIFO clocks in sync
        # with the FPGA's fabric. Accordingly, we'll need to capture the output clocks and then
        # pass them back to the SerDes; this allows the placer to handle clocking correctly, allows us
        # to attach clock constraints for analysis, and allows us to use these clocks for -very- simple tasks.
        txoutclk = Signal()
        rxoutclk = Signal()


        # Internal state.
        rx_los     = Signal()
        rx_lol     = Signal()
        rx_lsm     = Signal()
        rx_align   = Signal()
        rx_bus     = Signal(24)

        tx_lol     = Signal()
        tx_bus     = Signal(24)


        #
        # Clock domain crossing.
        #
        tx_produce_square_wave = Signal()
        tx_produce_pattern     = Signal()
        tx_pattern             = Signal(20)

        m.submodules += [
            # Transmit control  synchronization.
            FFSynchronizer(self.tx_produce_square_wave, tx_produce_square_wave, o_domain="tx"),
            FFSynchronizer(self.tx_produce_pattern, tx_produce_pattern, o_domain="tx"),
            FFSynchronizer(self.tx_pattern, tx_pattern, o_domain="tx"),

            # Receive control synchronization.
            FFSynchronizer(self.rx_align, rx_align, o_domain="rx"),
            FFSynchronizer(rx_los, self.rx_idle, o_domain="sync"),
        ]

        #
        # Clocking / reset control.
        #

        # Create a local transmit domain, for our transmit-side hardware.
        m.domains.tx = ClockDomain()
        m.d.comb    += ClockSignal("tx").eq(txoutclk)
        m.submodules += [
            ResetSynchronizer(ResetSignal("sync"), domain="tx"),
            FFSynchronizer(~ResetSignal("tx"), self.tx_ready)
        ]

        # Create the same setup, buf for the receive side.
        m.domains.rx = ClockDomain()
        m.d.comb    += ClockSignal("rx").eq(rxoutclk)
        m.submodules += [
            ResetSynchronizer(ResetSignal("sync"), domain="rx"),
            FFSynchronizer(~ResetSignal("rx"), self.rx_ready)
        ]

        # TODO: set up proper clock domain constraints for our Tx and Rx domains.
        # Currently, we're omitting these; as nextpnr can't correctly deal with false
        # paths created during our clock domain crossing.
        #
        #   self.tx_clk_freq = pll.config["linerate"]/data_width
        #   self.rx_clk_freq = pll.config["linerate"]/data_width
        #   platform.add_clock_constraint(serdes.txoutclk, serdes.tx_clk_freq)
        #   platform.add_clock_constraint(serdes.rxoutclk, serdes.rx_clk_freq)
        #   platform.add_false_path_constraints(sys_clk, serdes.cd_tx.clk, serdes.cd_rx.clk)

        #
        # SerDes register translation & SCI interface.
        #
        m.submodules.sci = sci = ECP5SerDesConfigInterface(self)
        m.submodules.sci_reconfig = sci_control = ECP5SerDesRegisterTranslator(self, sci)
        m.d.comb += [
            sci_control.loopback.eq(self.loopback),
            sci_control.tx_idle.eq(self.tx_idle),
            sci_control.rx_polarity.eq(self.rx_invert),
            sci_control.tx_polarity.eq(self.tx_invert)
        ]

        #
        # Core SerDes instantiation.
        #
        serdes_params = dict(
            # DCU — power management
            p_D_MACROPDB            = "0b1",
            p_D_IB_PWDNB            = "0b1",    # undocumented (required for RX)
            p_D_TXPLL_PWDNB         = "0b1",
            i_D_FFC_MACROPDB        = 1,

            # DCU — reset
            i_D_FFC_MACRO_RST       = ResetSignal("sync"),
            i_D_FFC_DUAL_RST        = ResetSignal("sync"),

            # DCU — clocking
            i_D_REFCLKI             = self._pll.refclk,
            o_D_FFS_PLOL            = tx_lol,
            p_D_REFCK_MODE          = {
                25: "0b100",
                20: "0b000",
                16: "0b010",
                10: "0b001",
                 8: "0b011"}[self._pll.config["mult"]],
            p_D_TX_MAX_RATE         = "5.0",    # 5.0 Gbps
            p_D_TX_VCO_CK_DIV       = {
                32: "0b111",
                16: "0b110",
                 8: "0b101",
                 4: "0b100",
                 2: "0b010",
                 1: "0b000"}[1],                # DIV/1
            p_D_BITCLK_LOCAL_EN     = "0b1",    # Use clock from local PLL

            # DCU ­— unknown
            p_D_CMUSETBIASI         = "0b00",   # begin undocumented (10BSER sample code used)
            p_D_CMUSETI4CPP         = "0d3",
            p_D_CMUSETI4CPZ         = "0d3",
            p_D_CMUSETI4VCO         = "0b00",
            p_D_CMUSETICP4P         = "0b01",
            p_D_CMUSETICP4Z         = "0b101",
            p_D_CMUSETINITVCT       = "0b00",
            p_D_CMUSETISCL4VCO      = "0b000",
            p_D_CMUSETP1GM          = "0b000",
            p_D_CMUSETP2AGM         = "0b000",
            p_D_CMUSETZGM           = "0b000",
            p_D_SETIRPOLY_AUX       = "0b01",
            p_D_SETICONST_AUX       = "0b01",
            p_D_SETIRPOLY_CH        = "0b01",
            p_D_SETICONST_CH        = "0b10",
            p_D_SETPLLRC            = "0d1",
            p_D_RG_EN               = "0b0",
            p_D_RG_SET              = "0b00",
            p_D_REQ_ISET            = "0b011",
            p_D_PD_ISET             = "0b11",   # end undocumented

            # DCU — FIFOs
            p_D_LOW_MARK            = "0d4",    # Clock compensation FIFO low  water mark (mean=8)
            p_D_HIGH_MARK           = "0d12",   # Clock compensation FIFO high water mark (mean=8)

            # CHX common ---------------------------------------------------------------------------
            # CHX — protocol
            p_CHX_PROTOCOL          = "G8B10B",
            p_CHX_UC_MODE           = "0b1",

            p_CHX_ENC_BYPASS        = "0b0",    # Bypass 8b10b encoder
            p_CHX_DEC_BYPASS        = "0b0",    # Bypass 8b10b decoder

            # CHX receive --------------------------------------------------------------------------
            # CHX RX ­— power management
            p_CHX_RPWDNB            = "0b1",
            i_CHX_FFC_RXPWDNB       = 1,

            # CHX RX ­— reset
            i_CHX_FFC_RRST          = ~self.rx_enable,
            i_CHX_FFC_LANE_RX_RST   = ~self.rx_enable,

            # CHX RX ­— input
            i_CHX_HDINP             = self._rx_pads.p,
            i_CHX_HDINN             = self._rx_pads.n,

            p_CHX_REQ_EN            = "0b1",    # Enable equalizer
            p_CHX_REQ_LVL_SET       = "0b11",
            p_CHX_RX_RATE_SEL       = "0d10",   # Equalizer  pole position
            p_CHX_RTERM_RX          = {
                "5k-ohms":        "0b00000",
                "80-ohms":        "0b00001",
                "75-ohms":        "0b00100",
                "70-ohms":        "0b00110",
                "60-ohms":        "0b01011",
                "50-ohms":        "0b10011",
                "46-ohms":        "0b11001",
                "wizard-50-ohms": "0d22"}["50-ohms"],
            p_CHX_RXIN_CM           = "0b11",   # CMFB (wizard value used)
            p_CHX_RXTERM_CM         = "0b11",   # RX Input (wizard value used)

            # CHX RX ­— clocking
            i_CHX_RX_REFCLK         = self._pll.refclk,
            o_CHX_FF_RX_PCLK        = rxoutclk,
            i_CHX_FF_RXI_CLK        = ClockSignal("rx"),

            p_CHX_CDR_MAX_RATE      = "5.0",    # 5.0 Gbps
            p_CHX_RX_DCO_CK_DIV     = {
                32: "0b111",
                16: "0b110",
                 8: "0b101",
                 4: "0b100",
                 2: "0b010",
                 1: "0b000"}[1],                # DIV/1
            p_CHX_RX_GEAR_MODE      = "0b1",    # 1:2 gearbox
            p_CHX_FF_RX_H_CLK_EN    = "0b1",    # enable  DIV/2 output clock
            p_CHX_FF_RX_F_CLK_DIS   = "0b1",    # disable DIV/1 output clock
            p_CHX_SEL_SD_RX_CLK     = "0b1",    # FIFO driven by recovered clock

            p_CHX_AUTO_FACQ_EN      = "0b1",    # undocumented (wizard value used)
            p_CHX_AUTO_CALIB_EN     = "0b1",    # undocumented (wizard value used)
            p_CHX_PDEN_SEL          = "0b0",    # phase detector disabled on LOS

            p_CHX_DCOATDCFG         = "0b00",   # begin undocumented (sample code used)
            p_CHX_DCOATDDLY         = "0b00",
            p_CHX_DCOBYPSATD        = "0b1",
            p_CHX_DCOCALDIV         = "0b000",
            p_CHX_DCOCTLGI          = "0b011",
            p_CHX_DCODISBDAVOID     = "0b0",
            p_CHX_DCOFLTDAC         = "0b00",
            p_CHX_DCOFTNRG          = "0b001",
            p_CHX_DCOIOSTUNE        = "0b010",
            p_CHX_DCOITUNE          = "0b00",
            p_CHX_DCOITUNE4LSB      = "0b010",
            p_CHX_DCOIUPDNX2        = "0b1",
            p_CHX_DCONUOFLSB        = "0b100",
            p_CHX_DCOSCALEI         = "0b01",
            p_CHX_DCOSTARTVAL       = "0b010",
            p_CHX_DCOSTEP           = "0b11",   # end undocumented

            # CHX RX — loss of signal
            o_CHX_FFS_RLOS          = rx_los,
            p_CHX_RLOS_SEL          = "0b1",
            p_CHX_RX_LOS_EN         = "0b0",
            p_CHX_RX_LOS_LVL        = "0b101",  # Lattice "TBD" (wizard value used)
            p_CHX_RX_LOS_CEQ        = "0b11",   # Lattice "TBD" (wizard value used)
            p_CHX_RX_LOS_HYST_EN    = "0b1",

            # CHX RX — loss of lock
            o_CHX_FFS_RLOL          = rx_lol,

            # CHX RX — link state machine
            # Note that Lattice Diamond needs these in their provided bases (and string lengths!).
            # Changing their bases will work with the open toolchain, but will make Diamond mad.
            i_CHX_FFC_SIGNAL_DETECT = rx_align,
            o_CHX_FFS_LS_SYNC_STATUS= rx_lsm,
            p_CHX_ENABLE_CG_ALIGN   = "0b1",
            p_CHX_UDF_COMMA_MASK    = "0x0ff",  # compare the 8 lsbs
            p_CHX_UDF_COMMA_A       = "0x003",   # "0b0000000011", # K28.1, K28.5 and K28.7
            p_CHX_UDF_COMMA_B       = "0x07c",   # "0b0001111100", # K28.1, K28.5 and K28.7

            p_CHX_CTC_BYPASS        = "0b1",    # bypass CTC FIFO
            p_CHX_MIN_IPG_CNT       = "0b11",   # minimum interpacket gap of 4
            p_CHX_MATCH_2_ENABLE    = "0b0",    # 2 character skip matching
            p_CHX_MATCH_4_ENABLE    = "0b0",    # 4 character skip matching
            p_CHX_CC_MATCH_1        = "0x000",
            p_CHX_CC_MATCH_2        = "0x000",
            p_CHX_CC_MATCH_3        = "0x000",
            p_CHX_CC_MATCH_4        = "0x000",

            # CHX RX — data
            **{"o_CHX_FF_RX_D_%d" % n: rx_bus[n] for n in range(len(rx_bus))},

            # CHX transmit -------------------------------------------------------------------------
            # CHX TX — power management
            p_CHX_TPWDNB            = "0b1",
            i_CHX_FFC_TXPWDNB       = 1,

            # CHX TX ­— reset
            i_D_FFC_TRST            = ~self.tx_enable,
            i_CHX_FFC_LANE_TX_RST   = ~self.tx_enable,

            # CHX TX ­— output
            o_CHX_HDOUTP            = self._tx_pads.p,
            o_CHX_HDOUTN            = self._tx_pads.n,

            p_CHX_TXAMPLITUDE       = "0d1000",  # 1000 mV
            p_CHX_RTERM_TX          = {
                "5k-ohms":        "0b00000",
                "80-ohms":        "0b00001",
                "75-ohms":        "0b00100",
                "70-ohms":        "0b00110",
                "60-ohms":        "0b01011",
                "50-ohms":        "0b10011",
                "46-ohms":        "0b11001",
                "wizard-50-ohms": "0d19"}["wizard-50-ohms"],

            p_CHX_TDRV_SLICE0_CUR   = "0b011",  # 400 uA
            p_CHX_TDRV_SLICE0_SEL   = "0b01",   # main data
            p_CHX_TDRV_SLICE1_CUR   = "0b000",  # 100 uA
            p_CHX_TDRV_SLICE1_SEL   = "0b00",   # power down
            p_CHX_TDRV_SLICE2_CUR   = "0b11",   # 3200 uA
            p_CHX_TDRV_SLICE2_SEL   = "0b01",   # main data
            p_CHX_TDRV_SLICE3_CUR   = "0b10",   # 2400 uA
            p_CHX_TDRV_SLICE3_SEL   = "0b01",   # main data
            p_CHX_TDRV_SLICE4_CUR   = "0b00",   # 800 uA
            p_CHX_TDRV_SLICE4_SEL   = "0b00",   # power down
            p_CHX_TDRV_SLICE5_CUR   = "0b00",   # 800 uA
            p_CHX_TDRV_SLICE5_SEL   = "0b00",   # power down

            # CHX TX ­— clocking
            o_CHX_FF_TX_PCLK        = txoutclk,
            i_CHX_FF_TXI_CLK        = ClockSignal("tx"),

            p_CHX_TX_GEAR_MODE      = "0b1",    # 1:2 gearbox
            p_CHX_FF_TX_H_CLK_EN    = "0b1",    # enable  DIV/2 output clock
            p_CHX_FF_TX_F_CLK_DIS   = "0b1",    # disable DIV/1 output clock

            # CHX TX — data
            **{"i_CHX_FF_TX_D_%d" % n: tx_bus[n] for n in range(len(tx_bus))},

            # SCI interface.
            **{"i_D_SCIWDATA%d" % n: sci.sci_wdata[n] for n in range(8)},
            **{"i_D_SCIADDR%d"   % n: sci.sci_addr[n] for n in range(6)},
            **{"o_D_SCIRDATA%d" % n: sci.sci_rdata[n] for n in range(8)},
            i_D_SCIENAUX  = sci.dual_sel,
            i_D_SCISELAUX = sci.dual_sel,
            i_CHX_SCIEN   = sci.chan_sel,
            i_CHX_SCISEL  = sci.chan_sel,
            i_D_SCIRD     = sci.sci_rd,
            i_D_SCIWSTN   = sci.sci_wrn,

            # Out-of-band signaling Rx support.
            p_CHX_LDR_RX2CORE_SEL     = "0b1",            # Enables low-speed out-of-band input.
            o_CHX_LDR_RX2CORE         = self.rx_gpio,

            # Out-of-band signaling Tx support.
            p_CHX_LDR_CORE2TX_SEL     = "0b0",            # Uses CORE2TX_EN to enable out-of-band output.
            i_CHX_LDR_CORE2TX         = self.tx_gpio,
            i_CHX_FFC_LDR_CORE2TX_EN  = self.tx_gpio_en
        )

        # Translate the 'CHX' string to the correct channel name in each of our SerDes parameters,
        # and create our SerDes instance.
        serdes_params = {k.replace("CHX", f"CH{self._channel}"):v for (k,v) in serdes_params.items()}
        m.submodules.serdes = serdes = Instance("DCUA", **serdes_params)

        # Bind our SerDes to the correct location inside the FPGA.
        serdes.attrs["LOC"] = "DCU{}".format(self._dual)
        serdes.attrs["CHAN"] = "CH{}".format(self._channel)
        serdes.attrs["BEL"] = "X42/Y71/DCU"

        #
        # TX and RX datapaths (SerDes <-> stream conversion)
        #
        sink   = self.sink
        source = self.source

        m.d.comb += [
            # Grab our received data directly from our SerDes; modifying things to match the
            # SerDes Rx bus layout, which squishes status signals between our two geared words.
            source.data[0: 8]  .eq(rx_bus[ 0: 8]),
            source.data[8:16]  .eq(rx_bus[12:20]),
            source.ctrl[0]     .eq(rx_bus[8]),
            source.ctrl[1]     .eq(rx_bus[20]),
            source.valid       .eq(1),

            # Stick the data we'd like to transmit into the SerDes; again modifying things to match
            # the transmit bus layout.
            tx_bus[ 0: 8]      .eq(sink.data[0: 8]),
            tx_bus[12:20]      .eq(sink.data[8:16]),
            tx_bus[8]          .eq(sink.ctrl[0]),
            tx_bus[20]         .eq(sink.ctrl[1]),
            sink.ready         .eq(1)
        ]


        return m



class LunaECP5SerDes(Elaboratable):
    """ Wrapper around the core ECP5 SerDes that optimizes the SerDes for USB3 use. """

    def __init__(self, platform, sys_clk, sys_clk_freq, refclk_pads, refclk_freq, tx_pads, rx_pads, channel):
        self._primary_clock           = sys_clk
        self._primary_clock_frequency = sys_clk_freq
        self._refclk                  = refclk_pads
        self._refclk_frequency        = refclk_freq
        self._tx_pads                 = tx_pads
        self._rx_pads                 = rx_pads
        self._channel                 = channel

        #
        # I/O port
        #
        self.sink   = USBRawSuperSpeedStream()
        self.source = USBRawSuperSpeedStream()

        self.enable = Signal(reset=1) # i
        self.ready  = Signal()        # o

        self.tx_polarity = Signal()   # i
        self.tx_idle     = Signal()   # i
        self.tx_pattern  = Signal(20) # i

        self.rx_polarity = Signal()   # i
        self.rx_idle     = Signal()   # o
        self.rx_align    = Signal()   # i

        # GPIO interface.
        self.use_tx_as_gpio = Signal()
        self.tx_gpio        = Signal()
        self.rx_gpio        = Signal()

        # Debug interface.
        self.raw_rx_data    = Signal(16)
        self.raw_rx_ctrl    = Signal(2)


    def elaborate(self, platform):
        m = Module()

        #
        # Reference clock selection.
        #

        # If we seem to have a raw pin record, we'll assume we're being passed the external REFCLK.
        # We'll instantiate an instance that captures the reference clock signal.
        if hasattr(self._refclk, 'p'):
            refclk = Signal()
            m.submodules.refclk_input = refclk_in = Instance("EXTREFB",
                i_REFCLKP     = self._refclk.p,
                i_REFCLKN     = self._refclk.n,
                o_REFCLKO     = refclk,
                p_REFCK_PWDNB = "0b1",
                p_REFCK_RTERM = "0b1", # 100 Ohm
            )
            refclk_in.attrs["LOC"] =  "EXTREF0"

        # Otherwise, we'll accept the reference clock directly.
        else:
            refclk = self._refclk

        #
        # Raw serdes.
        #
        pll_config = ECP5SerDesPLLConfiguration(refclk, refclk_freq=self._refclk_frequency, linerate=5e9)
        serdes  = ECP5SerDes(
            pll_config  = pll_config,
            tx_pads     = self._tx_pads,
            rx_pads     = self._rx_pads,
            channel     = self._channel,
        )
        m.submodules.serdes = serdes
        m.d.comb += self.ready.eq(serdes.tx_ready & serdes.rx_ready),


        #
        # Transmit datapath.
        #
        m.submodules.tx_datapath = tx_datapath = TxDatapath("tx")
        m.d.comb += [
            serdes.tx_idle             .eq(self.tx_idle),
            serdes.tx_enable           .eq(self.enable),

            tx_datapath.sink           .stream_eq(self.sink),
            serdes.sink                .stream_eq(tx_datapath.source),

            serdes.tx_gpio_en          .eq(self.use_tx_as_gpio),
            serdes.tx_gpio             .eq(self.tx_gpio)
        ]


        #
        # Receive datapath.
        #
        m.submodules.rx_datapath = rx_datapath = RxDatapath("rx")

        m.d.comb += [
            self.rx_idle            .eq(serdes.rx_idle),

            serdes.rx_enable        .eq(self.enable),
            serdes.rx_align         .eq(self.rx_align),
            rx_datapath.align       .eq(self.rx_align),

            rx_datapath.sink        .stream_eq(serdes.source),
            self.source             .stream_eq(rx_datapath.source)
        ]

        # Pass through a synchronized version of our SerDes' rx-gpio.
        m.submodules += FFSynchronizer(serdes.rx_gpio, self.rx_gpio, o_domain="fast")

        # debug signals
        m.d.comb += [
            self.raw_rx_data.eq(serdes.source.data),
            self.raw_rx_ctrl.eq(serdes.source.ctrl),
        ]

        return m
