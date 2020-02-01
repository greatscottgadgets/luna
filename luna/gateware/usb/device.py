#
# This file is part of LUNA.
#
""" Low-level USB transciever gateware -- exposes packet interfaces. """

import unittest

from nmigen            import Signal, Module, Elaboratable, Memory
from nmigen.back.pysim import Simulator

from ...test           import LunaGatewareTestCase, ulpi_domain_test_case, sync_test_case
from ...utils          import rising_edge_detector, falling_edge_detector

from ..ulpi            import UMTITranslator


