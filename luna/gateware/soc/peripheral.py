#
# This file is part of LUNA.
#
# Adapted from lambdasoc.
# This file includes content Copyright (C) 2020 LambdaConcept.
#
# Per our BSD license, derivative files must include this license disclaimer.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

""" Peripheral helpers for LUNA devices. """

from contextlib import contextmanager

from amaranth                import Module, Elaboratable
from amaranth                import tracer
from amaranth.utils          import log2_int

from amaranth_soc              import csr, wishbone
from amaranth_soc.memory       import MemoryMap
from amaranth_soc.csr.wishbone import WishboneCSRBridge

from .event                  import EventSource, IRQLine, InterruptSource


__all__ = ["Peripheral", "CSRBank", "PeripheralBridge"]


class Peripheral:
    """Wishbone peripheral.

    A helper class to reduce the boilerplate needed to control a peripheral with a Wishbone interface.
    It provides facilities for instantiating CSR registers, requesting windows to subordinate busses
    and sending interrupt requests to the CPU.

    The ``Peripheral`` class is not meant to be instantiated as-is, but rather as a base class for
    actual peripherals.

    Usage example
    -------------

    ```
    class ExamplePeripheral(Peripheral, Elaboratable):
        def __init__(self):
            super().__init__()
            bank         = self.csr_bank()
            self._foo    = bank.csr(8, "r")
            self._bar    = bank.csr(8, "w")

            self._rdy    = self.event(mode="rise")

            self._bridge = self.bridge(data_width=32, granularity=8, alignment=2)
            self.bus     = self._bridge.bus
            self.irq     = self._bridge.irq

        def elaborate(self, platform):
            m = Module()
            m.submodules.bridge = self._bridge
            # ...
            return m
    ```

    Arguments
    ---------
    name : str
        Name of this peripheral. If ``None`` (default) the name is inferred from the variable
        name this peripheral is assigned to.

    Properties
    ----------
    name : str
        Name of the peripheral.
    """
    def __init__(self, name=None, src_loc_at=1):
        if name is not None and not isinstance(name, str):
            raise TypeError("Name must be a string, not {!r}".format(name))
        self.name      = name or tracer.get_var_name(depth=2 + src_loc_at).lstrip("_")

        self._csr_banks = []
        self._windows   = []
        self._events    = []

        self._bus       = None
        self._irq       = None

    @property
    def bus(self):
        """Wishbone bus interface.

        Return value
        ------------
        An instance of :class:`Interface`.

        Exceptions
        ----------
        Raises :exn:`NotImplementedError` if the peripheral does not have a Wishbone bus.
        """
        if self._bus is None:
            raise NotImplementedError("Peripheral {!r} does not have a bus interface"
                                      .format(self))
        return self._bus

    @bus.setter
    def bus(self, bus):
        if not isinstance(bus, wishbone.Interface):
            raise TypeError("Bus interface must be an instance of wishbone.Interface, not {!r}"
                            .format(bus))
        self._bus = bus

    @property
    def irq(self):
        """Interrupt request line.

        Return value
        ------------
        An instance of :class:`IRQLine`.

        Exceptions
        ----------
        Raises :exn:`NotImplementedError` if the peripheral does not have an IRQ line.
        """
        if self._irq is None:
            raise NotImplementedError("Peripheral {!r} does not have an IRQ line"
                                      .format(self))
        return self._irq

    @irq.setter
    def irq(self, irq):
        if not isinstance(irq, IRQLine):
            raise TypeError("IRQ line must be an instance of IRQLine, not {!r}"
                            .format(irq))
        self._irq = irq

    def csr_bank(self, *, addr=None, alignment=None, desc=None):
        """Request a CSR bank.

        Arguments
        ---------
        addr : int or None
            Address of the bank. If ``None``, the implicit next address will be used.
            Otherwise, the exact specified address (which must be a multiple of
            ``2 ** max(alignment, bridge_alignment)``) will be used.
        alignment : int or None
            Alignment of the bank. If not specified, the bridge alignment is used.
            See :class:`amaranth_soc.csr.Multiplexer` for details.
        desc: (str, optional):
            Documentation of the given CSR bank.

        Return value
        ------------
        An instance of :class:`CSRBank`.
        """
        bank = CSRBank(name_prefix=self.name)
        self._csr_banks.append((bank, addr, alignment))
        return bank

    def window(self, *, addr_width, data_width, granularity=None, features=frozenset(),
               alignment=0, addr=None, sparse=None):
        """Request a window to a subordinate bus.

        See :meth:`amaranth_soc.wishbone.Decoder.add` for details.

        Return value
        ------------
        An instance of :class:`amaranth_soc.wishbone.Interface`.
        """
        window = wishbone.Interface(addr_width=addr_width, data_width=data_width,
                                    granularity=granularity, features=features)
        granularity_bits = log2_int(data_width // window.granularity)
        window.memory_map = MemoryMap(addr_width=addr_width + granularity_bits,
                                      data_width=window.granularity, alignment=alignment)
        self._windows.append((window, addr, sparse))
        return window

    def event(self, *, mode="level", name=None, src_loc_at=0, desc=None):
        """Request an event source.

        See :class:`EventSource` for details.

        Return value
        ------------
        An instance of :class:`EventSource`.
        """
        event = EventSource(mode=mode, name=name, src_loc_at=1 + src_loc_at)
        self._events.append(event)
        return event

    def bridge(self, *, data_width=8, granularity=None, features=frozenset(), alignment=0):
        """Request a bridge to the resources of the peripheral.

        See :class:`PeripheralBridge` for details.

        Return value
        ------------
        A :class:`PeripheralBridge` providing access to local resources.
        """
        return PeripheralBridge(self, data_width=data_width, granularity=granularity,
                                features=features, alignment=alignment)

    def iter_csr_banks(self):
        """Iterate requested CSR banks and their parameters.

        Yield values
        ------------
        A tuple ``bank, addr, alignment`` describing the bank and its parameters.
        """
        for bank, addr, alignment in self._csr_banks:
            yield bank, addr, alignment

    def iter_windows(self):
        """Iterate requested windows and their parameters.

        Yield values
        ------------
        A tuple ``window, addr, sparse`` descr
        given to :meth:`Peripheral.window`.
        """
        for window, addr, sparse in self._windows:
            yield window, addr, sparse

    def iter_events(self):
        """Iterate requested event sources.

        Yield values
        ------------
        An instance of :class:`EventSource`.
        """
        for event in self._events:
            yield event


class CSRBank:
    """CSR register bank.

    Parameters
    ----------
    name_prefix : str
        Name prefix of the bank registers.
    """
    def __init__(self, *, name_prefix=""):
        self._name_prefix = name_prefix
        self._csr_regs    = []

    def csr(self, width, access, *, addr=None, alignment=None, name=None, desc=None,
            src_loc_at=0):
        """Request a CSR register.

        Parameters
        ----------
        width : int
            Width of the register. See :class:`amaranth_soc.csr.Element`.
        access : :class:`Access`
            Register access mode. See :class:`amaranth_soc.csr.Element`.
        addr : int
            Address of the register. See :meth:`amaranth_soc.csr.Multiplexer.add`.
        alignment : int
            Register alignment. See :class:`amaranth_soc.csr.Multiplexer`.
        name : str
            Name of the register. If ``None`` (default) the name is inferred from the variable
            name this register is assigned to.
        desc: str
            Documentation for the provided register, if available.
            Used to capture register documentation automatically.


        Return value
        ------------
        An instance of :class:`amaranth_soc.csr.Element`.
        """
        if name is not None and not isinstance(name, str):
            raise TypeError("Name must be a string, not {!r}".format(name))
        name = name or tracer.get_var_name(depth=2 + src_loc_at).lstrip("_")

        elem_name = "{}_{}".format(self._name_prefix, name)
        elem = csr.Element(width, access, name=elem_name)
        self._csr_regs.append((elem, addr, alignment))
        return elem

    def iter_csr_regs(self):
        """Iterate requested CSR registers and their parameters.

        Yield values
        ------------
        A tuple ``elem, addr, alignment`` describing the register and its parameters.
        """
        for elem, addr, alignment in self._csr_regs:
            yield elem, addr, alignment


class PeripheralBridge(Elaboratable):
    """Peripheral bridge.

    A bridge providing access to the registers and windows of a peripheral, and support for
    interrupt requests from its event sources.

    Event managment is performed by an :class:`InterruptSource` submodule.

    Parameters
    ---------
    periph : :class:`Peripheral`
        The peripheral whose resources are exposed by this bridge.
    data_width : int
        Data width. See :class:`amaranth_soc.wishbone.Interface`.
    granularity : int or None
        Granularity. See :class:`amaranth_soc.wishbone.Interface`.
    features : iter(str)
        Optional signal set. See :class:`amaranth_soc.wishbone.Interface`.
    alignment : int
        Resource alignment. See :class:`amaranth_soc.memory.MemoryMap`.

    Attributes
    ----------
    bus : :class:`amaranth_soc.wishbone.Interface`
        Wishbone bus providing access to the resources of the peripheral.
    irq : :class:`IRQLine`, out
        Interrupt request. It is raised if any event source is enabled and has a pending
        notification.
    """
    def __init__(self, periph, *, data_width, granularity, features, alignment):
        if not isinstance(periph, Peripheral):
            raise TypeError("Peripheral must be an instance of Peripheral, not {!r}"
                            .format(periph))

        self._wb_decoder = wishbone.Decoder(addr_width=1, data_width=data_width,
                                            granularity=granularity,
                                            features=features, alignment=alignment)

        self._csr_subs = []

        for bank, bank_addr, bank_alignment in periph.iter_csr_banks():
            if bank_alignment is None:
                bank_alignment = alignment
            csr_mux = csr.Multiplexer(addr_width=1, data_width=8, alignment=bank_alignment)
            for elem, elem_addr, elem_alignment in bank.iter_csr_regs():
                if elem_alignment is None:
                    elem_alignment = alignment
                csr_mux.add(elem, addr=elem_addr, alignment=elem_alignment, extend=True)

            csr_bridge = WishboneCSRBridge(csr_mux.bus, data_width=data_width)
            self._wb_decoder.add(csr_bridge.wb_bus, addr=bank_addr, extend=True)
            self._csr_subs.append((csr_mux, csr_bridge))

        for window, window_addr, window_sparse in periph.iter_windows():
            self._wb_decoder.add(window, addr=window_addr, sparse=window_sparse, extend=True)

        events = list(periph.iter_events())
        if len(events) > 0:
            self._int_src = InterruptSource(events, name="{}_ev".format(periph.name))
            self.irq      = self._int_src.irq

            csr_mux = csr.Multiplexer(addr_width=1, data_width=8, alignment=alignment)
            csr_mux.add(self._int_src.status,  extend=True)
            csr_mux.add(self._int_src.pending, extend=True)
            csr_mux.add(self._int_src.enable,  extend=True)

            csr_bridge = WishboneCSRBridge(csr_mux.bus, data_width=data_width)
            self._wb_decoder.add(csr_bridge.wb_bus, extend=True)
            self._csr_subs.append((csr_mux, csr_bridge))
        else:
            self._int_src = None
            self.irq      = None

        self.bus = self._wb_decoder.bus

    def elaborate(self, platform):
        m = Module()

        for i, (csr_mux, csr_bridge) in enumerate(self._csr_subs):
            m.submodules[   "csr_mux_{}".format(i)] = csr_mux
            m.submodules["csr_bridge_{}".format(i)] = csr_bridge

        if self._int_src is not None:
            m.submodules._int_src = self._int_src

        m.submodules.wb_decoder = self._wb_decoder

        return m
