#!/usr/bin/env python3
"""Independent byte-array oracle for real native HIA 1GiB PDPTE writer.

The 1GiB feature is a caller-supplied CPUID capability, not a CPU
attestation. No physical CPU walk, CAS, TLB flush or SMP proof is claimed.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

PAGE = 4096
MASK64 = (1 << 64) - 1
NX = 1 << 63
NXE = 1 << 8
PGE = 1 << 9
PDPE1GB = 1 << 10
CAPS = 52 | NXE | PGE | PDPE1GB
PHYS = ((1 << 52) - 1) & ~((1 << 30) - 1)
ALLOWED = PHYS | 0x1fff | (0x7f << 52) | NX


def pack(slot: int, old: int, value: int, caps: int = CAPS) -> bytes:
    return struct.pack("<4Q", slot, old, value, caps)


def oracle(request: bytes, table: bytes, reply_size: int = 16):
    unchanged = bytes(table)
    if reply_size < 16:
        return 1, None, unchanged
    if len(request) != 32:
        return 2, 0, unchanged
    if len(table) != PAGE:
        return 4, 0, unchanged
    slot, old, candidate, caps = struct.unpack("<4Q", request)
    width = caps & 255
    if caps & ~0x7ff or not 32 <= width <= 52:
        return 8, 0, unchanged
    # A zero replacement removes an existing 1GiB leaf; validate the OLD
    # hardware entry, including reserved bits and CPU capabilities, before
    # the same full-word stale comparison used for ordinary commits.
    if candidate == 0:
        physical = old & PHYS
        if (not old & 1 or not old & 128 or old & ~ALLOWED
                or physical >= 1 << width):
            return 6, 0, unchanged
        if (not caps & PDPE1GB or
                (old & NX and not caps & NXE) or
                (old & 256 and not caps & PGE)):
            return 8, 0, unchanged
    else:
        physical = candidate & PHYS
        if (candidate & ~ALLOWED or not candidate & 1 or not candidate & 128
                or (candidate & 2 and not candidate & NX)
                or (candidate & 4 and candidate & 256)
                or physical >= 1 << width):
            return 6, 0, unchanged
        if (not caps & PDPE1GB or
                (candidate & NX and not caps & NXE) or
                (candidate & 256 and not caps & PGE)):
            return 8, 0, unchanged
    if slot >= 512:
        return 6, 0, unchanged
    if struct.unpack_from("<Q", unchanged, slot * 8)[0] != old:
        return 9, 0, unchanged
    changed = bytearray(unchanged)
    struct.pack_into("<Q", changed, slot * 8, candidate)
    return 0, candidate, bytes(changed)


def campaign(library: Path):
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    count = passed = refused = 0

    def check(raw: bytes, data: bytes, reply_size: int = 16):
        nonlocal count, passed, refused
        request = ctypes.create_string_buffer(b"\xa5" * 32 + raw + b"\xa5" * 32)
        reply = ctypes.create_string_buffer(b"\xb6" * (reply_size + 64))
        table = ctypes.create_string_buffer(b"\xc7" * 32 + data + b"\xc7" * 32)
        r0 = bytes(request)
        p0 = bytes(reply)
        expected, value, changed = oracle(raw, data, reply_size)
        got = native(ctypes.addressof(request) + 32, len(raw),
                     ctypes.addressof(reply) + 32, reply_size,
                     ctypes.addressof(table) + 32, len(data))
        assert bytes(request) == r0, "input mutation"
        assert bytes(table)[:32] == b"\xc7" * 32, "table underflow"
        assert bytes(table)[32:32+len(data)] == changed, "nonlocal table mutation"
        assert bytes(table)[32+len(data):32+len(data)+32] == b"\xc7" * 32, "table overflow"
        assert bytes(reply)[:32] == b"\xb6" * 32, "reply underflow"
        assert bytes(reply)[32+reply_size:32+reply_size+32] == b"\xb6" * 32, "reply overflow"
        assert got == expected, ("status", got, expected, raw.hex())
        if reply_size < 16:
            assert bytes(reply) == p0, "short reply mutation"
        else:
            assert struct.unpack_from("<2Q", reply, 32) == (expected, value)
            assert bytes(reply)[48:32+reply_size] == b"\xb6" * (reply_size - 16)
        count += 1
        passed += expected == 0
        refused += expected != 0

    rng = random.Random(0x1B6D1B6D)
    # Positive and negative control inputs, each in a fresh table with
    # arbitrary adjacent bytes. PAT uses bit 12 (never physical base).
    for slot in (0, 1, 255, 511, 512, MASK64):
        data = bytearray(rng.randbytes(PAGE))
        old = struct.unpack_from("<Q", data, (slot % 512) * 8)[0]
        for frame in (0, 1 << 30, 3 << 30, (1 << 52) - (1 << 30)):
            for flags in (0x81, 0x83, 0x85, 0x181, 0x1081,
                          0x481, 0x1000000000000081):
                for caps in (CAPS, CAPS & ~PDPE1GB, CAPS & ~NXE,
                             CAPS & ~PGE, 32 | NXE | PGE | PDPE1GB):
                    check(pack(slot, old, frame | NX | flags, caps), bytes(data))
        check(pack(slot, old ^ 1, NX | (1 << 30) | 0x81), bytes(data))
    # Each architecturally reserved bit 13..29 and PK-like bits 59..62
    # must be rejected even when PAT/software flags are legal.
    for bit in range(13, 30):
        request = pack(0, 0, NX | (1 << 30) | 0x1081 | (1 << bit))
        assert oracle(request, bytes(PAGE))[0] == 6
        check(request, bytes(PAGE))
    for bit in range(52, 63):
        request = pack(0, 0, NX | (1 << 30) | 0x1081 | (1 << bit))
        assert oracle(request, bytes(PAGE))[0] == (0 if bit <= 58 else 6)
        check(request, bytes(PAGE))
        check(pack(0, 1, NX | (1 << 30) | 0x1081 | (1 << bit)), bytes(PAGE))
    for bit in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
        req = pack(0, 0, NX | (1 << 30) | 0x81 | (1 << bit))
        check(req, bytes(PAGE))
    for i in range(1400):
        slot = rng.choice((0, 1, 511, 512, MASK64, rng.randrange(512)))
        data = bytearray(rng.randbytes(PAGE))
        old = struct.unpack_from("<Q", data, (slot % 512) * 8)[0]
        physical = rng.choice((0, 1 << 30, 2 << 30,
                               (1 << 52) - (1 << 30), rng.getrandbits(52)))
        candidate = rng.choice((NX | physical | 0x81,
                                NX | physical | 0x1083,
                                NX | physical | 0x85,
                                rng.getrandbits(64)))
        caps = rng.choice((CAPS, CAPS & ~PDPE1GB, CAPS & ~NXE,
                           CAPS & ~PGE, 52, 31 | NXE | PDPE1GB,
                           32 | NXE | PGE | PDPE1GB, 2048, MASK64))
        check(pack(slot, old if rng.randrange(5) else old ^ 1, candidate, caps), bytes(data))
    # 1GiB unmap/old-word-replay cases: a successful unmap must clear
    # exactly the selected PDPTE; the identical old word must then fail.
    for i in range(320):
        slot = rng.randrange(512)
        data = bytearray(rng.randbytes(PAGE))
        phys = rng.randrange(1, 1 << 17) << 30
        flags = rng.choice((0, 0x20, 0x40, 0x100, 0x1000,
                            (1 << 52), (1 << 55), 0x160))
        old = NX | phys | 0x81 | flags
        struct.pack_into("<Q", data, slot * 8, old)
        request = pack(slot, old, 0)
        assert oracle(request, bytes(data))[0] == 0
        check(request, bytes(data))
        struct.pack_into("<Q", data, slot * 8, 0)
        assert oracle(request, bytes(data))[0] == 9
        check(request, bytes(data))

    # Refuse non-huge, absent, reserved, too-wide and CPU-incompatible old
    # 1GiB leaves. These are distinct from stale-old mismatch.
    for old, caps, expected_status in (
        ((1 << 30) | 1, CAPS, 6),                 # missing PS
        ((1 << 30) | 128, CAPS, 6),               # missing Present
        ((1 << 30) | 0x81 | (1 << 13), CAPS, 6), # reserved address bit
        ((1 << 30) | 0x81 | (1 << 61), CAPS, 6), # unmodelled protection key
        ((1 << 40) | 0x81, 32 | NXE | PGE | PDPE1GB, 6),
        ((1 << 30) | 0x81, CAPS & ~PDPE1GB, 8),
        (NX | (1 << 30) | 0x81, CAPS & ~NXE, 8),
        ((1 << 30) | 0x181, CAPS & ~PGE, 8),
    ):
        data = bytearray(PAGE)
        struct.pack_into("<Q", data, 0, old)
        req = pack(0, old, 0, caps)
        assert oracle(req, bytes(data))[0] == expected_status
        check(req, bytes(data))

    for raw in (b"", b"\0" * 24, b"\0" * 31, b"\0" * 33):
        check(raw, bytes(PAGE))
    for length in (0, 1, 4095, 4096, 4097):
        check(pack(0, 0, NX | (1 << 30) | 0x81), bytes(length))
    for reply_size in (0, 1, 8, 15, 16, 17, 32):
        check(pack(0, 0, NX | (1 << 30) | 0x81), bytes(PAGE), reply_size)
    assert passed >= 100 and refused >= 100, (passed, refused)
    return {"schema": "heptakernel.x86-pdpt-1g.v1", "status": "PASS",
            "cases": count, "commits": passed, "refusals": refused,
            "independent_oracle": True, "native_hia": True,
            "smp_atomicity_verified": False, "qemu_hardware_tested": False, "unmap_hardware_tested": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--expect-unsafe", action="store_true")
    a = ap.parse_args()
    if a.expect_unsafe:
        try:
            campaign(a.library)
        except AssertionError as exc:
            print("dishonest 1GiB PDPTE native control rejected:", str(exc)[:240])
            return
        raise SystemExit("dishonest PDPTE implementation passed oracle")
    report = campaign(a.library)
    Path("build/x86-pdpt-1g-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("native HIA 1GiB PDPTE differential:", report)


if __name__ == "__main__":
    main()
