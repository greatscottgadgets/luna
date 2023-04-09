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

from amaranth                  import Module, Elaboratable
from amaranth                  import tracer
from amaranth.utils            import log2_int

from amaranth_soc              import csr, wishbone
from amaranth_soc.memory       import MemoryMap
from amaranth_soc.csr.wishbone import WishboneCSRBridge

from lambdasoc.periph.base     import PeripheralBridge
from lambdasoc.periph.event    import EventSource

import lambdasoc

__all__ = ["Peripheral", "CSRBank", "PeripheralBridge"]

# Note:
#
# The following are thin wrappers around LambdaSoC's Peripheral and
# CSRBank classes.
#
# The primary reason this abstraction exists is to allow us to support
# auto-generation of register documentation from Peripherals.
#
# The intention is to either upstream this at a future point in time
# or use LambdaSoC's facilities if/when it should gain them.

class Peripheral(lambdasoc.periph.base.Peripheral):
    def csr_bank(self, *, name=None, addr=None, alignment=None, desc=None):
        """Request a CSR bank.

        Arguments
        ---------
        name : str
            Optional. Bank name.
        addr : int or None
            Address of the bank. If ``None``, the implicit next address will be used.
            Otherwise, the exact specified address (which must be a multiple of
            ``2 ** max(alignment, bridge_alignment)``) will be used.
        alignment : int or None
            Alignment of the bank. If not specified, the bridge alignment is used.
            See :class:`amaranth_soc.csr.Multiplexer` for details.
        desc : str
            Optional. Documentation for the given CSR bank.

        Return value
        ------------
        An instance of :class:`CSRBank`.
        """
        bank = CSRBank(name=name)
        bank.desc = desc
        self._csr_banks.append((bank, addr, alignment))

        return bank

    def event(self, *, mode="level", name=None, src_loc_at=0, desc=None):
        """Request an event source.

        Arguments
        ---------
        desc : str
            Optional. Documentation for the given event.

        See :class:`EventSource` for details.

        Return value
        ------------
        An instance of :class:`EventSource`.
        """
        if name is None:
            name = tracer.get_var_name(depth=2 + src_loc_at).lstrip("_")

        event = super().event(mode=mode, name=name, src_loc_at=src_loc_at)

        event.desc = desc
        return event


class CSRBank(lambdasoc.periph.base.CSRBank):
    def csr(self, width, access, *, addr=None, alignment=None, name=None,
            src_loc_at=0, desc=None):
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
        desc : str
            Optional. Documentation for the given register.
            Used to generate register documentation automatically.

        Return value
        ------------
        An instance of :class:`amaranth_soc.csr.Element`.
        """
        if name is None:
            name = tracer.get_var_name(depth=2 + src_loc_at).lstrip("_")

        elem = super().csr(width, access, addr=addr, alignment=alignment, name=name, src_loc_at=src_loc_at)
        elem.desc = desc

        return elem
