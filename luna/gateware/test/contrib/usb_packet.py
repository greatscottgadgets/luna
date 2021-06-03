#!/usr/bin/env python3
#
# BSD 3-Clause License
#
# Copyright (c) 2018, Luke Valenty
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from .           import crc
from ...usb.usb2 import USBPacketID as PID


def b(s):
    """Byte string with LSB first into an integer.

    >>> b("1")
    1
    >>> b("01")
    2
    >>> b("101")
    5
    """
    return int(s[::-1], 2)


def encode_data(data):
    """
    Converts array of 8-bit ints into string of 0s and 1s.
    """
    output = ""

    for b in data:
        output += (f"{int(b):08b}")[::-1]

    return output


def encode_pid(value):
    if not isinstance(value, PID):
        value = PID(value)
    assert isinstance(value, PID), repr(value)
    return encode_data([value.byte()])


# width=5 poly=0x05 init=0x1f refin=true refout=true xorout=0x1f check=0x19
# residue=0x06 name="CRC-5/USB"
def crc5(nibbles):
    """
    >>> hex(crc5([0, 0]))
    '0x1'
    >>> hex(crc5([3, 0]))
    '0x13'
    """
    reg = crc.CrcRegister(crc.CRC5_USB)
    for n in nibbles:
        reg.takeWord(n, 4)
    return reg.getFinalValue() & 0x1f


def crc5_token(addr, ep):
    """
    >>> hex(crc5_token(0, 0))
    '0x2'
    >>> hex(crc5_token(92, 0))
    '0x1c'
    >>> hex(crc5_token(3, 0))
    '0xa'
    >>> hex(crc5_token(56, 4))
    '0xb'
    """
    reg = crc.CrcRegister(crc.CRC5_USB)
    reg.takeWord(addr, 7)
    reg.takeWord(ep, 4)
    return reg.getFinalValue()


def crc5_sof(v):
    """
    >>> hex(crc5_sof(1429))
    '0x10'
    >>> hex(crc5_sof(1013))
    '0x14'
    """
    reg = crc.CrcRegister(crc.CRC5_USB)
    reg.takeWord(v, 11)
    return eval('0b' + bin(reg.getFinalValue() | 0x10000000)[::-1][:5])


def crc16(input_data):
    # width=16 poly=0x8005 init=0xffff refin=true refout=true xorout=0xffff
    # check=0xb4c8 residue=0xb001 name="CRC-16/USB"
    # CRC appended low byte first.
    reg = crc.CrcRegister(crc.CRC16_USB)
    for d in input_data:
        assert d <= 0xff, input_data
        reg.takeWord(d, 8)
    crc16 = reg.getFinalValue()
    return [crc16 & 0xff, (crc16 >> 8) & 0xff]


def nrzi(data, cycles=4, init="J"):
    """Converts string of 0s and 1s into NRZI encoded string.

    >>> nrzi("11 00000001", 1)
    'JJ KJKJKJKK'

    It will do bit stuffing.
    >>> nrzi("1111111111", 1)
    'JJJJJJKKKKK'

    Support single ended zero
    >>> nrzi("1111111__", 1)
    'JJJJJJKK__'

    Support pre-encoded mixing.
    >>> nrzi("11kkj11__", 1)
    'JJKKJJJ__'

    Supports wider clock widths
    >>> nrzi("101", 4)
    'JJJJKKKKKKKK'
    """
    def toggle_state(state):
        if state == 'J':
            return 'K'
        if state == 'K':
            return 'J'
        return state

    state = init
    output = ""

    stuffed = []
    i = 0
    for bit in data:
        stuffed.append(bit)
        if bit == '1':
            i += 1
        else:
            i = 0
        if i > 5:
            stuffed.append('0')
            i = 0

    for bit in stuffed:
        if bit == ' ':
            output += bit
            continue

        # only toggle the state on '0'
        if bit == '0':
            state = toggle_state(state)
        elif bit == '1':
            pass
        elif bit in "jk_":
            state = bit.upper()
        else:
            assert False, "Unknown bit %s in %r" % (bit, data)

        output += (state * cycles)

    return output


def sync():
    return "kjkjkjkk"


def eop():
    return "__j"


def wrap_packet(data, cycles=4):
    """Add the sync + eop sections and do nrzi encoding.

    >>> wrap_packet(handshake_packet(PID.ACK), cycles=1)
    'KJKJKJKKJJKJJKKK__J'
    >>> wrap_packet(token_packet(PID.SETUP, 0, 0), cycles=1)
    'KJKJKJKKKJJJKKJKJKJKJKJKJKJKKJKJ__J'
    >>> wrap_packet(data_packet(PID.DATA0, [5, 6]), cycles=1)
    'KJKJKJKKKKJKJKKKKJJKJKJKJJJKJKJKKJJJJJJKKJJJJKJK__J'
    >>> wrap_packet(data_packet(PID.DATA0, [0x1]), cycles=1)
    'KJKJKJKKKKJKJKKKKJKJKJKJJKJKJKJJJJJJJKKKJ__J'

    """
    return nrzi(sync() + data + eop(), cycles)


def token_packet(pid, addr, endp):
    """Create a token packet for testing.

    sync, pid, addr (7bit), endp(4bit), crc5(5bit), eop

    >>> token_packet(PID.SETUP, 0x0, 0x0)
    '101101000000000000001000'

     PPPPPPPP                 - 8 bits - PID
             AAAAAAA          - 7 bits - ADDR
                    EEEE      - 4 bits - EP
                        CCCCC - 5 bits - CRC

    >>> token_packet(PID.IN, 0x3, 0x0) # 0x0A
    '100101101100000000001010'

    >>> token_packet(PID.OUT, 0x3a, 0xa)
    '100001110101110010111100'

    >>> token_packet(PID.SETUP, 0x70, 0xa)
    '101101000000111010110101'

    >>> token_packet(PID.SETUP, 40, 2)
    '101101000001010010000011'

    >>> token_packet(PID.SETUP, 28, 2)
    '101101000011100010001001'

     PPPPPPPP                 - 8 bits - PID
             AAAAAAA          - 7 bits - ADDR
                    EEEE      - 4 bits - EP
                        CCCCC - 5 bits - CRC
    """
    assert addr < 128, addr
    assert endp < 2**4, endp
    assert pid in (PID.OUT, PID.IN, PID.SETUP), pid
    token = encode_pid(pid)
    token += "{0:07b}".format(addr)[::-1]  # 7 bits address
    token += "{0:04b}".format(endp)[::-1]  # 4 bits endpoint
    token += "{0:05b}".format(crc5_token(addr, endp))[::-1]  # 5 bits CRC5
    assert len(token) == 24, token
    return token


def data_packet(pid, payload):
    """Create a data packet for testing.

    sync, pid, data, crc16, eop
    FIXME: data should be multiples of 8?

    >>> data_packet(PID.DATA0, [0x80, 0x06, 0x03, 0x03, 0x09, 0x04, 0x00,\
0x02])
    '1100001100000001011000001100000011000000100100000010000000000000010000000110101011011100'

    >>> data_packet(PID.DATA1, [])
    '110100100000000000000000'

    """
    assert pid in (PID.DATA0, PID.DATA1), pid
    payload = list(payload)
    return encode_pid(pid) + encode_data(payload + crc16(payload))


def handshake_packet(pid):
    """ Create a handshake packet for testing.

    sync, pid, eop
    ack / nak / stall / nyet (high speed only)

    >>> handshake_packet(PID.ACK)
    '01001011'
    >>> handshake_packet(PID.NAK)
    '01011010'
    """
    assert pid in (PID.ACK, PID.NAK, PID.STALL), pid
    return encode_pid(pid)


def sof_packet(frame):
    """Create a SOF packet for testing.

    sync, pid, frame no (11bits), crc5(5bits), eop

    >>> sof_packet(1)
    '101001011000000000010111'

    >>> sof_packet(100)
    '101001010010011000011111'

    >>> sof_packet(257)
    '101001011000000010000011'

    >>> sof_packet(1429)
    '101001011010100110110000'

    >>> sof_packet(2**11 - 2)
    '101001010111111111111101'
    """
    def rev_byte(x):
        return int("{0:08b}".format(x)[:8][::-1], 2)

    assert frame < 2**11, (frame, '<', 2**11)
    frame_rev = int("{0:011b}".format(frame)[:11][::-1], 2)
    data = [frame_rev >> 3, (frame_rev & 0b111) << 5]
    data[-1] = data[-1] | crc5_sof(frame)
    data[0] = rev_byte(data[0])
    data[1] = rev_byte(data[1])
    return encode_pid(PID.SOF) + encode_data(data)


def diff(value):
    """Convert J/K encoding into bits for P/N diff pair.

    >>> diff('KJ_')
    ('010', '100')

    >>> # Convert ACK handshake packet
    >>> p,n = diff('KJKJKJKKJJKJJKKK__J')
    >>> p
    '0101010011011000001'
    >>> n
    '1010101100100111000'
    """
    usbp = ""
    usbn = ""
    for i in range(len(value)):
        v = value[i]
        if v == ' ':
            continue
        elif v == '_':
            # SE0 - both lines pulled low
            usbp += "0"
            usbn += "0"
        elif v == 'J':
            usbp += "1"
            usbn += "0"
        elif v == 'K':
            usbp += "0"
            usbn += "1"
        else:
            assert False, "Unknown value: %s" % v
    return usbp, usbn


def undiff(usbp, usbn):
    """Convert P/N diff pair bits into J/K encoding.

    >>> from cocotb_usb.usb.pp_packet import pp_packet
    >>> undiff(
    ...   #EJK_
    ...   '1100', # p
    ...   '1010', # n
    ... )
    'EJK_'
    >>> print(pp_packet(undiff(
    ...   #KJKJKJKKJJKJJKKK__J - ACK handshake packet
    ...   '0101010011011000001', # p
    ...   '1010101100100111000', # n
    ... ), cycles=1))
    -
    K 1 Sync
    J 2 Sync
    K 3 Sync
    J 4 Sync
    K 5 Sync
    J 6 Sync
    K 7 Sync
    K 8 Sync
    -
    J 1 PID (PID.ACK)
    J 2 PID
    K 3 PID
    J 4 PID
    J 5 PID
    K 6 PID
    K 7 PID
    K 8 PID
    -
    _ SE0
    _ SE0
    J END
    >>> print(pp_packet(undiff(*diff(wrap_packet(sof_packet(0))))))
    ----
    KKKK 1 Sync
    JJJJ 2 Sync
    KKKK 3 Sync
    JJJJ 4 Sync
    KKKK 5 Sync
    JJJJ 6 Sync
    KKKK 7 Sync
    KKKK 8 Sync
    ----
    KKKK 1 PID (PID.SOF)
    JJJJ 2 PID
    JJJJ 3 PID
    KKKK 4 PID
    JJJJ 5 PID
    JJJJ 6 PID
    KKKK 7 PID
    KKKK 8 PID
    ----
    JJJJ  1 Frame #
    KKKK  2 Frame #
    JJJJ  3 Frame #
    KKKK  4 Frame #
    JJJJ  5 Frame #
    KKKK  6 Frame #
    JJJJ  7 Frame #
    KKKK  8 Frame #
    ----
    JJJJ  9 Frame #
    KKKK 10 Frame #
    JJJJ 11 Frame #
    KKKK 1 CRC5
    KKKK 2 CRC5
    JJJJ 3 CRC5
    KKKK 4 CRC5
    JJJJ 5 CRC5
    ----
    ____ SE0
    ____ SE0
    JJJJ END
    """
    assert len(usbp) == len(
        usbn), "Sequence different lengths!\n%s\n%s\n" % (usbp, usbn)
    value = []
    for i in range(0, len(usbp)):
        p = usbp[i]
        n = usbn[i]
        value.append({
            # pn
            '00': '_',
            '11': 'E',
            '10': 'J',
            '01': 'K',
        }[p + n])
    return "".join(value)


if __name__ == "__main__":
    import doctest
    doctest.testmod()
