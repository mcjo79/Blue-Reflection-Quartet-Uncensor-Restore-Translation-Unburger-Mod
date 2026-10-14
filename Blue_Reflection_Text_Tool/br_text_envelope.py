"""BLUE REFLECTION text-envelope codec (``strcombineall.xml.e``).

This is a faithful Python port of the deterministic codec implemented by the
native patcher in ``Blue_Reflection_Patcher/internal/br1rebuild/text_envelope.go``.
The runtime reads the encrypted ``strcombineall.xml.e`` sibling, so any patch
that changes the plain ``strcombineall.xml`` must regenerate its envelope.

The codec is self-contained and deterministic: encoding the same plaintext
always produces byte-identical output.

Public API
----------
``encode_br_text_envelope(plain) -> bytes``
``decode_br_text_envelope(encoded) -> bytes``
``BR1_SEEDS`` / ``SECOND_LIGHT_A21_SEEDS``

CLI
---
``python br_text_envelope.py decode INPUT.e OUTPUT.xml``
``python br_text_envelope.py encode INPUT.xml OUTPUT.e``
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Any


class TextEnvelopeError(RuntimeError):
    """Raised when a text envelope cannot be encoded or decoded."""


BR1_SEEDS: dict[str, Any] = {
    "main": (0x6947, 0xCB63, 0x7597),
    "table": (0xA829, 0xB047, 0x8AF5),
    "length": (0x1D, 0x13, 0x0B),
    "fence": 0x0B23,
}

# A21 profile used by BLUE REFLECTION: Second Light for encrypted XML table
# siblings (for example stream.xml.e).
SECOND_LIGHT_A21_SEEDS: dict[str, Any] = {
    "main": (0x6D3F, 0xCB53, 0x74B9),
    "table": (0xA83B, 0xB11D, 0x88A5),
    "length": (0x1D, 0x13, 0x0B),
    "fence": 0x0A31,
}

_U32 = 0xFFFFFFFF
_U16 = 0xFFFF
_HEADER_SPAN = 0x800


class _TextPRNG:
    __slots__ = ("mul", "state")

    def __init__(self, offset: int, state: int) -> None:
        self.mul = (0x3B9A73C9 + offset) & _U32
        self.state = state & _U32

    def u15(self) -> int:
        self.state = (self.mul * self.state + 0x2F09) & _U32
        return (self.state >> 16) & 0x7FFF

    def u16(self) -> int:
        self.state = (self.mul * self.state + 0x2F09) & _U32
        return (self.state >> 16) & _U16


def _swap_bits(buf: bytearray, base: int, a: int, b: int) -> None:
    ap, ab = a >> 3, a & 7
    bp, bb = b >> 3, b & 7
    av = (buf[base + ap] >> ab) & 1
    bv = (buf[base + bp] >> bb) & 1
    buf[base + ap] = ((buf[base + ap] & ~(1 << ab)) | (bv << ab)) & 0xFF
    buf[base + bp] = ((buf[base + bp] & ~(1 << bb)) | (av << bb)) & 0xFF


def _shuffle_text_bits(
    buf: bytearray,
    start: int,
    end: int,
    slice_bytes: int,
    rng: _TextPRNG,
    reverse: bool,
) -> None:
    """Bit-shuffle ``buf[start:end]`` in ``slice_bytes`` sized spans."""
    span_total = end - start
    if span_total < 0:
        raise TextEnvelopeError("invalid text bit-slice range")
    if slice_bytes <= 0 or slice_bytes * 8 < 4:
        raise TextEnvelopeError("invalid text bit-slice size")

    off = 0
    while off < span_total:
        span = min(slice_bytes, span_total - off)
        bit_count = span * 8
        available = list(range(bit_count))
        order = [0] * bit_count
        for i in range(bit_count):
            pick = rng.u15() % (bit_count - i)
            order[i] = available[pick]
            del available[pick]

        if reverse:
            for i in range(0, bit_count, 2):
                _swap_bits(buf, start + off, order[i], order[i + 1])
        else:
            for i in range(bit_count - 2, -1, -2):
                _swap_bits(buf, start + off, order[i], order[i + 1])
        off += slice_bytes


def _rotate_text_bytes(buf: bytearray, seeds: dict[str, Any], rng: _TextPRNG) -> None:
    """XOR the buffer with the seeded key stream (symmetric)."""
    states = list(seeds["table"])
    lengths = list(seeds["length"])
    index = 0
    cycle_extra = 0
    processed = 0
    for i in range(len(buf)):
        buf[i] ^= rng.u16() & 0xFF
        processed += 1
        if processed >= lengths[index] + cycle_extra:
            states[index] = rng.state
            index += 1
            if index == len(states):
                index = 0
                cycle_extra += 1
            rng.state = states[index]
            processed = 0


def _fence_text_words(
    buf: bytearray,
    start: int,
    end: int,
    fence: int,
    rng: _TextPRNG,
    reverse: bool,
) -> None:
    if (end - start) % 2 != 0:
        raise TextEnvelopeError("text envelope word span is not aligned")
    limit = fence * 2
    for pos in range(start, end, 2):
        x = rng.u15()
        w = struct.unpack_from(">H", buf, pos)[0]
        if reverse:
            if x % limit >= fence:
                w ^= x
            w = (w - x) & _U16
        else:
            w = (w + x) & _U16
            if x % limit >= fence:
                w ^= x
        struct.pack_into(">H", buf, pos, w)


def _adler32(buf: bytes | bytearray) -> int:
    mod = 65521
    a, b = 1, 0
    for value in buf:
        a = (a + value) % mod
        b = (b + a) % mod
    return ((b << 16) | a) & _U32


def _checksum_sub(buf: bytes | bytearray) -> int:
    total = 0
    for i in range(0, len(buf) - 3, 4):
        total = (total - struct.unpack_from(">I", buf, i)[0]) & _U32
    return total


def _checksum_xor(buf: bytes | bytearray) -> int:
    total = 0
    for i in range(0, len(buf) - 3, 4):
        total ^= (~struct.unpack_from(">I", buf, i)[0]) & _U32
    return total & _U32


def _literal_text_stream(src: bytes) -> tuple[bytes, int]:
    """Build the literal-copy stream (opcode 00111 for every 256-byte block)."""
    if len(src) < 14:
        raise TextEnvelopeError("text payload is too small")
    rem = len(src) % 256
    blocks = (len(src) + 255) // 256
    merge_tail = blocks > 1 and 0 < rem <= 13
    if merge_tail:
        blocks -= 1
    if blocks <= 0:
        raise TextEnvelopeError("text payload cannot be represented")

    bits = blocks * 5
    bit_bytes = (bits + 7) // 8
    out = bytearray(12 + bit_bytes + 4 + len(src) + 4 + blocks)
    struct.pack_into(">I", out, 0, len(src))
    struct.pack_into(">I", out, 4, bit_bytes + 4)
    struct.pack_into(">I", out, 8, blocks)

    bit_pos = 0
    for _ in range(blocks):
        for bit in range(4, -1, -1):
            if (7 >> bit) & 1:
                out[12 + bit_pos // 8] |= 1 << (7 - (bit_pos % 8))
            bit_pos += 1

    pos = 12 + bit_bytes
    struct.pack_into(">I", out, pos, len(src))
    pos += 4
    out[pos:pos + len(src)] = src
    pos += len(src)
    struct.pack_into(">I", out, pos, blocks)
    pos += 4
    for i in range(blocks - 1):
        out[pos + i] = 242
    last = rem
    if rem == 0:
        last = 256
    elif merge_tail:
        last += 256
    out[pos + blocks - 1] = (last - 14) & 0xFF
    return bytes(out), blocks


def _unwrap_literal_text_stream(src: bytes) -> bytes:
    if len(src) < 20:
        raise TextEnvelopeError("text stream header is truncated")
    plain_size = struct.unpack_from(">I", src, 0)[0]
    stream_span = struct.unpack_from(">I", src, 4)[0]
    blocks = struct.unpack_from(">I", src, 8)[0]
    if plain_size < 0 or stream_span < 4 or blocks <= 0 or 8 + stream_span + 4 > len(src):
        raise TextEnvelopeError("text stream header is invalid")

    bit_bytes = stream_span - 4
    stream = src[12:12 + bit_bytes]
    bit_pos = 0
    for _ in range(blocks):
        code = 0
        for _ in range(5):
            if bit_pos // 8 >= len(stream):
                raise TextEnvelopeError("text stream opcode table is truncated")
            code = (code << 1) | ((stream[bit_pos // 8] >> (7 - (bit_pos % 8))) & 1)
            bit_pos += 1
        if code != 7:
            raise TextEnvelopeError(f"unsupported text stream opcode {code}")

    pos = 12 + bit_bytes
    if pos + 4 > len(src):
        raise TextEnvelopeError("text stream dictionary header is truncated")
    dict_size = struct.unpack_from(">I", src, pos)[0]
    pos += 4
    if dict_size < 0 or pos + dict_size + 4 > len(src):
        raise TextEnvelopeError("text stream dictionary is truncated")
    dictionary = src[pos:pos + dict_size]
    pos += dict_size
    length_count = struct.unpack_from(">I", src, pos)[0]
    pos += 4
    if length_count != blocks or pos + length_count > len(src):
        raise TextEnvelopeError("text stream length table is invalid")

    lengths = src[pos:pos + length_count]
    out = bytearray()
    dict_pos = 0
    for raw in lengths:
        n = raw + 14
        if dict_pos + n > len(dictionary):
            raise TextEnvelopeError("text stream dictionary copy exceeds bounds")
        out += dictionary[dict_pos:dict_pos + n]
        dict_pos += n
    if len(out) != plain_size or dict_pos != dict_size:
        raise TextEnvelopeError("text stream decoded length mismatch")
    return bytes(out)


def encode_text_envelope(plain: bytes, seeds: dict[str, Any]) -> bytes:
    stream, code_bytes = _literal_text_stream(plain)
    working = len(plain)
    if len(stream) + code_bytes > working:
        working = len(stream) + code_bytes

    payload = bytearray(stream)
    check2 = _adler32(payload)
    begin = min(len(payload), _HEADER_SPAN)
    _shuffle_text_bits(payload, 0, begin, 0x80, _TextPRNG(check2, seeds["main"][2]), False)
    check0 = _checksum_sub(payload)
    check1 = _checksum_xor(payload)
    _rotate_text_bytes(payload, seeds, _TextPRNG(check2, seeds["table"][0]))

    aligned = (len(payload) + 1 + 15) & ~15
    main = bytearray(aligned + 16)
    main[:len(payload)] = payload
    main[len(payload)] = 0xFF
    struct.pack_into(">I", main, aligned + 4, check0)
    struct.pack_into(">I", main, aligned + 8, check1)
    struct.pack_into(">I", main, aligned + 12, check2)
    _fence_text_words(main, 0, len(main), seeds["fence"], _TextPRNG(0, seeds["main"][1]), False)

    end = min(len(main), _HEADER_SPAN)
    _shuffle_text_bits(main, len(main) - end, len(main), 0x100, _TextPRNG(0, seeds["main"][0]), False)

    out = bytearray(16 + len(main))
    struct.pack_into(">I", out, 0, 2)
    struct.pack_into(">I", out, 4, working)
    out[16:] = main
    return bytes(out)


def decode_text_envelope(encoded: bytes, seeds: dict[str, Any]) -> bytes:
    if len(encoded) <= 32 or len(encoded) % 4 != 0:
        raise TextEnvelopeError("text envelope size is invalid")
    if struct.unpack_from(">I", encoded, 0)[0] != 2:
        raise TextEnvelopeError("unsupported text envelope version")
    working = struct.unpack_from(">I", encoded, 4)[0]
    if working == 0 or working > 256 * 1024 * 1024:
        raise TextEnvelopeError("text envelope workspace is invalid")

    main = bytearray(encoded[16:])
    end = min(len(main), _HEADER_SPAN)
    _shuffle_text_bits(main, len(main) - end, len(main), 0x100, _TextPRNG(0, seeds["main"][0]), True)
    _fence_text_words(main, 0, len(main), seeds["fence"], _TextPRNG(0, seeds["main"][1]), True)

    if len(main) < 16:
        raise TextEnvelopeError("text envelope footer is missing")
    aligned = len(main) - 16
    check0 = struct.unpack_from(">I", main, aligned + 4)[0]
    check1 = struct.unpack_from(">I", main, aligned + 8)[0]
    check2 = struct.unpack_from(">I", main, aligned + 12)[0]

    marker = aligned
    while marker > 0 and main[marker] != 0xFF:
        marker -= 1
    if marker < 4 or main[marker] != 0xFF:
        raise TextEnvelopeError("text envelope end marker is missing")

    payload = main[:marker]
    _rotate_text_bytes(payload, seeds, _TextPRNG(check2, seeds["table"][0]))
    if _checksum_sub(payload) != check0 or _checksum_xor(payload) != check1:
        raise TextEnvelopeError("text envelope checksum mismatch")

    begin = min(len(payload), _HEADER_SPAN)
    _shuffle_text_bits(payload, 0, begin, 0x80, _TextPRNG(check2, seeds["main"][2]), True)
    plain = _unwrap_literal_text_stream(bytes(payload))
    if len(plain) > working:
        raise TextEnvelopeError("text envelope workspace is too small")
    return plain


def encode_br_text_envelope(plain: bytes) -> bytes:
    return encode_text_envelope(plain, BR1_SEEDS)


def decode_br_text_envelope(encoded: bytes) -> bytes:
    return decode_text_envelope(encoded, BR1_SEEDS)


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in {"encode", "decode"}:
        print(__doc__)
        return 2
    mode, source, destination = argv[1], Path(argv[2]), Path(argv[3])
    data = source.read_bytes()
    if mode == "encode":
        result = encode_br_text_envelope(data)
    else:
        result = decode_br_text_envelope(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result)
    print(f"{mode}: {source} -> {destination} ({len(data)} -> {len(result)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
