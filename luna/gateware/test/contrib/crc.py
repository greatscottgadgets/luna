#!/usr/bin/python3
# -*- Mode: Python; py-indent-offset: 4 -*-
#
# Copyright (C) 2005,2007  Ray Burr
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

# DISCLAIMER: I don't pretend to be a math wizard.  I don't have a
# deep understanding of all of the theory behind CRCs.  Part of the
# reason I originally wrote this is to help understand and verify CRC
# algorithms in practice.  It is likely that some of my terminology is
# inaccurate.

# Requires at least Python 2.4; tested with 2.4 and 2.5.
"""
This module can model common CRC algorithms given the set of defining
parameters.  This is intended to be easy to use for experimentation
rather than optimized for speed.  It is slow even for a native Python
CRC implementation.

Several common CRC algorithms are predefined in this module.

:authors: Ray Burr
:license: MIT License
:contact: http://www.nightmare.com/~ryb/

Examples
========

  >>> '%X' % CRC32.calcString('123456789')
  'CBF43926'

This test function runs all of the defined algorithms on the test
input string '123456789':

  >>> _printResults()
  CRC-5-USB: 19
  CRC-8-SMBUS: F4
  CRC-15: 059E
  CRC-16: BB3D
  CRC-16-USB: B4C8
  CRC-CCITT: 29B1
  CRC-HDLC: 906E
  CRC-24: 21CF02
  CRC-32: CBF43926
  CRC-32C: E3069283
  CRC-64: 46A5A9388A5BEFFE
  CRC-256: 79B96BDC0C519B239BE759EC0688C86FD25A3F4DF1E7F054AD1F923D0739DAC8

Calculating in parts:

  >>> value = CRC32.calcString('1234')
  >>> '%X' % CRC32.calcString('56789', value)
  'CBF43926'

Or, done a different way:

  >>> crc = CrcRegister(CRC32)
  >>> crc.takeString('1234')
  >>> crc.takeString('56789')
  >>> '%X' % crc.getFinalValue()
  'CBF43926'

Inversion of a CRC function:

  >>> CRC_CCITT.reverse().reflect().calcWord(54321, 16, 0)
  1648
  >>> CRC_CCITT.calcWord(_, 16, 0)
  54321

A 15-bit CRC is used in CAN protocols.  The following sample CAN frame
(in binary here) is converted to hexadecimal for the calcWord call.
The bits after the 15-bit CRC are not included in the CRC::

  0 11101000001 0 0 0 0001 00010010 011000010111011 1 1 1 1111111

This sample CAN frame was found in this paper:
<http://www.anthony-marino.com/documents/HDL_implementation_CAN.pdf>

  >>> '%X' % CRC15.calcWord(0x3A08112, 27)
  '30BB'

If the CRC is included, the remainder should always be zero:

  >>> print(CRC15.calcWord(0x1D0408930BB, 42))
  0

A 5-bit CRC is used some kinds of USB packets.  Here is a sample
start-of-frame packet:

  10100101 01100111000 01111

(found at <http://www.nital.com/corporate/usb2snooper.html>)

The first field is the PID (not included in the CRC), the next 11-bit
field is the frame number (0xE6, LSb-first order), and the final five
bits are the CRC (0x1E, LSb-first order).

  >>> '%X' % CRC5_USB.calcWord(0xE6, 11)
  '1E'
"""

# <http://docutils.sourceforge.net/docs/ref/rst/restructuredtext.html>
__docformat__ = "restructuredtext en"

__version__ = "20070611"


class CrcAlgorithm:
    """
    Represents the parameters of a CRC algorithm.
    """

    # FIXME: Instances are supposed to be immutable, but attributes are
    # writable.

    def __init__(self,
                 width,
                 polynomial,
                 name=None,
                 seed=0,
                 lsbFirst=False,
                 lsbFirstData=None,
                 xorMask=0):
        """
        :param width:

          The number of bits in the CRC register, or equivalently, the
          degree of the polynomial.

        :type width:

          an integer

        :param polynomial:

          The generator polynomial as a sequence of exponents

        :type polynomial:

          sequence or integer

        :param name:

          A name identifying algorithm.

        :type name:

          *str*

        :param seed:

          The initial value to load into the register.  (This is the
          value without *xorMask* applied.)

        :type seed:

          an integer

        :param lsbFirst:

          If ``true``, the register shifts toward the
          least-significant bit (sometimes called the *reflected* or
          *reversed* algorithim).  Otherwise, the register shifts
          toward the most-significant bit.

        :type lsbFirst:

          *bool*

        :param lsbFirstData:

          If ``true``, input data is taken least-significant bit
          first.  Otherwise, data is taken most-significant bit first.
          If ``None`` or not given, the value of *lsbFirst* is used.

        :type lsbFirstData:

          *bool*

        :param xorMask:

          An integer mask indicating which bits should be inverted
          when returning the final result.  This is also used for the
          input value if provided.

        :type xorMask:

          an integer
        """

        if width > 0:
            try:
                polyMask = int(polynomial)
            except TypeError:
                # Guess it is already a sequence of exponents.
                polynomial = list(polynomial)
                polynomial.sort()
                polynomial.reverse()
                polynomial = tuple(polynomial)
            else:
                # Convert a mask to a tuple of exponents.
                if lsbFirst:
                    polyMask = reflect(polyMask, width)
                polynomial = (width, )
                for i in range(width - 1, -1, -1):
                    if (polyMask >> i) & 1:
                        polynomial += (i, )

            if polynomial[:1] != (width, ):
                ValueError("mismatch between width and polynomial degree")

        self.width = width
        self.polynomial = polynomial
        self.name = name
        self.seed = seed
        self.lsbFirst = lsbFirst
        self.lsbFirstData = lsbFirstData
        self.xorMask = xorMask

        if not hasattr(width, "__rlshift__"):
            raise ValueError

        # FIXME: Need more checking of parameters.

    def __repr__(self):
        info = ""
        if self.name is not None:
            info = ' "%s"' % str(self.name)
        result = "<%s.%s%s @ %#x>" % (self.__class__.__module__,
                                      self.__class__.__name__, info, id(self))
        return result

    def calcString(self, s, value=None):
        """
        Calculate the CRC of the 8-bit string *s*.
        """
        r = CrcRegister(self, value)
        r.takeString(s)
        return r.getFinalValue()

    def calcWord(self, word, width, value=None):
        """
        Calculate the CRC of the integer *word* as a sequence of
        *width* bits.
        """
        r = CrcRegister(self, value)
        r.takeWord(word, width)
        return r.getFinalValue()

    def reflect(self):
        """
        Return the algorithm with the bit-order reversed.
        """
        ca = CrcAlgorithm(0, 0)
        ca._initFromOther(self)
        ca.lsbFirst = not self.lsbFirst
        if self.lsbFirstData is not None:
            ca.lsbFirstData = not self.lsbFirstData
        if ca.name:
            ca.name += " reflected"
        return ca

    def reverse(self):
        """
        Return the algorithm with the reverse polynomial.
        """
        ca = CrcAlgorithm(0, 0)
        ca._initFromOther(self)
        ca.polynomial = [(self.width - e) for e in self.polynomial]
        ca.polynomial.sort()
        ca.polynomial.reverse()
        ca.polynomial = tuple(ca.polynomial)
        if ca.name:
            ca.name += " reversed"
        return ca

    def _initFromOther(self, other):
        self.width = other.width
        self.polynomial = other.polynomial
        self.name = other.name
        self.seed = other.seed
        self.lsbFirst = other.lsbFirst
        self.lsbFirstData = other.lsbFirstData
        self.xorMask = other.xorMask


class CrcRegister:
    """
    Holds the intermediate state of the CRC algorithm.
    """
    def __init__(self, crcAlgorithm, value=None):
        """
        :param crcAlgorithm:

          The CRC algorithm to use.

        :type crcAlgorithm:

          `CrcAlgorithm`

        :param value:

          The initial register value to use.  The result previous of a
          previous CRC calculation, can be used here to continue
          calculation with more data.  If this parameter is ``None``
          or not given, the register will be initialized with
          algorithm's default seed value.

        :type value:

          an integer
        """

        self.crcAlgorithm = crcAlgorithm
        p = crcAlgorithm

        self.bitMask = (1 << p.width) - 1

        word = 0
        for n in p.polynomial:
            word |= 1 << n
        self.polyMask = word & self.bitMask

        if p.lsbFirst:
            self.polyMask = reflect(self.polyMask, p.width)

        if p.lsbFirst:
            self.inBitMask = 1 << (p.width - 1)
            self.outBitMask = 1
        else:
            self.inBitMask = 1
            self.outBitMask = 1 << (p.width - 1)

        if p.lsbFirstData is not None:
            self.lsbFirstData = p.lsbFirstData
        else:
            self.lsbFirstData = p.lsbFirst

        self.reset()

        if value is not None:
            self.value = value ^ p.xorMask

    def __str__(self):
        return formatBinaryString(self.value, self.crcAlgorithm.width)

    def reset(self):
        """
        Reset the state of the register with the default seed value.
        """
        self.value = int(self.crcAlgorithm.seed)

    def takeBit(self, bit):
        """
        Process a single input bit.
        """
        outBit = ((self.value & self.outBitMask) != 0)
        if self.crcAlgorithm.lsbFirst:
            self.value >>= 1
        else:
            self.value <<= 1
        self.value &= self.bitMask
        if outBit ^ bool(bit):
            self.value ^= self.polyMask

    def takeWord(self, word, width=8):
        """
        Process a binary input word.

        :param word:

          The input word.  Since this can be a Python ``long``, there
          is no coded limit to the number of bits the word can
          represent.

        :type word:

          an integer

        :param width:

          The number of bits *word* represents.

        :type width:

          an integer
        """
        if self.lsbFirstData:
            bitList = list(range(0, width))
        else:
            bitList = list(range(width - 1, -1, -1))
        for n in bitList:
            self.takeBit((word >> n) & 1)

    def takeString(self, s):
        """
        Process a string as input.  It is handled as a sequence of
        8-bit integers.
        """
        for c in s:
            self.takeWord(ord(c))

    def getValue(self):
        """
        Return the current value of the register as an integer.
        """
        return self.value

    def getFinalValue(self):
        """
        Return the current value of the register as an integer with
        *xorMask* applied.  This can be used after all input data is
        processed to obtain the final result.
        """
        p = self.crcAlgorithm
        return self.value ^ p.xorMask


def reflect(value, width):
    return sum(((value >> x) & 1) << (width - 1 - x) for x in range(width))


def formatBinaryString(value, width):
    return "".join("01" [(value >> i) & 1] for i in range(width - 1, -1, -1))


# Some standard algorithms are defined here.  I believe I was able to
# verify the correctness of each of these in some way (against an
# existing implementation or sample data with a known result).

#: Same CRC algorithm as Python's zlib.crc32
CRC32 = CrcAlgorithm(name="CRC-32",
                     width=32,
                     polynomial=(32, 26, 23, 22, 16, 12, 11, 10, 8, 7, 5, 4, 2,
                                 1, 0),
                     seed=0xFFFFFFFF,
                     lsbFirst=True,
                     xorMask=0xFFFFFFFF)

CRC16 = CrcAlgorithm(name="CRC-16",
                     width=16,
                     polynomial=(16, 15, 2, 0),
                     seed=0x0000,
                     lsbFirst=True,
                     xorMask=0x0000)

#: Used in USB data packets.
CRC16_USB = CrcAlgorithm(name="CRC-16-USB",
                         width=16,
                         polynomial=(16, 15, 2, 0),
                         seed=0xFFFF,
                         lsbFirst=True,
                         xorMask=0xFFFF)

CRC_CCITT = CrcAlgorithm(name="CRC-CCITT",
                         width=16,
                         polynomial=(16, 12, 5, 0),
                         seed=0xFFFF,
                         lsbFirst=False,
                         xorMask=0x0000)

#: This is the algorithm used in X.25 and for the HDLC 2-byte FCS.
CRC_HDLC = CrcAlgorithm(name="CRC-HDLC",
                        width=16,
                        polynomial=(16, 12, 5, 0),
                        seed=0xFFFF,
                        lsbFirst=True,
                        xorMask=0xFFFF)

#: Used in ATM HEC and SMBus.
CRC8_SMBUS = CrcAlgorithm(name="CRC-8-SMBUS",
                          width=8,
                          polynomial=(8, 2, 1, 0),
                          seed=0,
                          lsbFirst=False,
                          xorMask=0)

#: Used in RFC-2440 and MIL STD 188-184.
CRC24 = CrcAlgorithm(name="CRC-24",
                     width=24,
                     polynomial=(24, 23, 18, 17, 14, 11, 10, 7, 6, 5, 4, 3, 1,
                                 0),
                     seed=0xB704CE,
                     lsbFirst=False,
                     xorMask=0)

#: Used in Controller Area Network frames.
CRC15 = CrcAlgorithm(name="CRC-15",
                     width=15,
                     polynomial=(15, 14, 10, 8, 7, 4, 3, 0),
                     seed=0,
                     lsbFirst=False,
                     xorMask=0)

#: Used in iSCSI (RFC-3385); usually credited to Guy Castagnoli.
CRC32C = CrcAlgorithm(name="CRC-32C",
                      width=32,
                      polynomial=(32, 28, 27, 26, 25, 23, 22, 20, 19, 18, 14,
                                  13, 11, 10, 9, 8, 6, 0),
                      seed=0xFFFFFFFF,
                      lsbFirst=True,
                      xorMask=0xFFFFFFFF)

#: CRC used in USB Token and Start-Of-Frame packets
CRC5_USB = CrcAlgorithm(name="CRC-5-USB",
                        width=5,
                        polynomial=(5, 2, 0),
                        seed=0x1F,
                        lsbFirst=True,
                        xorMask=0x1F)

#: ISO 3309
CRC64 = CrcAlgorithm(name="CRC-64",
                     width=64,
                     polynomial=(64, 4, 3, 1, 0),
                     seed=0,
                     lsbFirst=True,
                     xorMask=0)

#: This is just to show off the ability to handle a very wide CRC.
# If this is a standard, I don't know where it is from.  I found the
# polynomial on a web page of an apparent Czech "Lady Killer"
# <http://www.volny.cz/lk77/crc256mmx/>.
POLYNOM256 = 0x82E2443E6320383A20B8A2A0A1EA91A3CCA99A30C5205038349C82AAA3A8FD27
CRC256 = CrcAlgorithm(
    name="CRC-256",
    width=256,
    polynomial=POLYNOM256,
    seed=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
    lsbFirst=True,
    xorMask=0)

# For the following I haven't found complete information and/or have
# no way to verify the result.  I started with the list on Wikipedia
# <http://en.wikipedia.org/wiki/Cyclic_redundancy_check>.
#
# CRC4_ITU = CrcAlgorithm(
#    name         = "CRC-4-ITU",
#    width        = 4,
#    polynomial   = (4, 1, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC5_ITU = CrcAlgorithm(
#    name         = "CRC-5-ITU",
#    width        = 5,
#    polynomial   = (5, 4, 2, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC6_ITU = CrcAlgorithm(
#    name         = "CRC-6-ITU",
#    width        = 6,
#    polynomial   = (6, 1, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC7 = CrcAlgorithm(
#    name         = "CRC-7",
#    width        = 7,
#    polynomial   = (7, 3, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC8_CCITT = CrcAlgorithm(
#    name         = "CRC-8-CCITT",
#    width        = 8,
#    polynomial   = (8, 7, 3, 2, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC8_DALLAS = CrcAlgorithm(
#    name         = "CRC-8-Dallas",
#    width        = 8,
#    polynomial   = (8, 5, 4, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC8 = CrcAlgorithm(
#    name         = "CRC-8",
#    width        = 8,
#    polynomial   = (8, 7, 6, 4, 2, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC8_J1850 = CrcAlgorithm(
#    name         = "CRC-8-J1850",
#    width        = 8,
#    polynomial   = (8, 4, 3, 2, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC10 = CrcAlgorithm(
#    name         = "CRC-10",
#    width        = 10,
#    polynomial   = (10, 9, 5, 4, 1, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC12 = CrcAlgorithm(
#    name         = "CRC-12",
#    width        = 12,
#    polynomial   = (12, 11, 3, 2, 1, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)
#
# CRC64_ECMA182 = CrcAlgorithm(
#    name         = "CRC-64-ECMA-182",
#    width        = 64,
#    polynomial   = (64, 62, 57, 55, 54, 53, 52, 47, 46, 45, 40, 39, 38, 37,
#                    35, 33, 32, 31, 29, 27, 24, 23, 22, 21, 19, 17, 13, 12,
#                    10, 9, 7, 4, 1, 0),
#    seed         = ?,
#    lsbFirst     = ?,
#    xorMask      = ?)


def _callCalcString123456789(v):
    return v.calcString('123456789')


def _printResults(fn=_callCalcString123456789):
    import sys
    d = sys.modules[__name__].__dict__
    algorithms = sorted(
        (v for (k, v) in d.items() if isinstance(v, CrcAlgorithm)),
        key=lambda v: (v.width, v.name))
    for a in algorithms:
        format = ("%%0%dX" % ((a.width + 3) // 4))
        print("%s:" % a.name, end=' ')
        print(format % fn(a))


def _test():
    import doctest
    import sys
    return doctest.testmod(sys.modules[__name__])


if __name__ == "__main__":
    _test()

