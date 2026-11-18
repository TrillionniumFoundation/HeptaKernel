#!/usr/bin/env python3
"""Byte-level independent oracle: quiescent native HIA 4KiB PTE RW downgrade.

This checks only an exact-old, single-owner writable+NX -> readonly+NX
transition. It does not prove atomicity, TLB shootdown, or Linux mprotect.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import random
import struct
from pathlib import Path

PAGE = 4096
MASK64 = (1 << 64) - 1
NX = 1 << 63
NXE = 1 << 8
PGE = 1 << 9
PA_MASK = ((1 << 52) - 1) & ~(PAGE - 1)
CAPS = 52 | NXE | PGE

def oracle(raw: bytes, table: bytes, reply_size: int = 16):
    original = bytes(table)
    if reply_size < 16:
        return 1, None, original
    if len(raw) != 32:
        return 2, 0, original
    if len(table) != PAGE:
        return 4, 0, original
    slot, expected, candidate, caps = struct.unpack("<4Q", raw)
    width = caps & 255
    if caps & ~0x3ff or not 32 <= width <= 52:
        return 8, 0, original
    # A/D, PAT, software, cache and global bits must be preserved exactly.
    eligible = (
        (expected & 3) == 3 and (expected & NX) == NX
        and not (expected & (0xF << 59))
        and (expected & PA_MASK) < (1 << width)
        and not ((expected & 4) and (expected & 256))
        and candidate == expected - 2
    )
    if not eligible:
        return 6, 0, original
    if not caps & NXE or ((expected & 256) and not caps & PGE):
        return 8, 0, original
    if slot >= 512:
        return 6, 0, original
    if struct.unpack_from("<Q", original, slot * 8)[0] != expected:
        return 9, 0, original
    updated = bytearray(original)
    struct.pack_into("<Q", updated, slot * 8, candidate)
    return 0, candidate, bytes(updated)


def pack(slot: int, old: int, new: int, caps: int = CAPS):
    return struct.pack("<4Q", slot, old, new, caps)

def campaign(path: Path):
    native = ctypes.CDLL(str(path.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    rng = random.Random(0xB0AFC0DE)
    counts = {"cases": 0, "allowed": 0, "refused": 0}

    def check(raw: bytes, table: bytes, reply_size: int = 16):
        request = ctypes.create_string_buffer(b"\xa5" * 32 + raw + b"\xa5" * 32)
        reply = ctypes.create_string_buffer(b"\xb6" * (reply_size + 64))
        memory = ctypes.create_string_buffer(b"\xc7" * 32 + table + b"\xc7" * 32)
        before_req, before_reply = bytes(request), bytes(reply)
        result = native(ctypes.addressof(request) + 32, len(raw),
                        ctypes.addressof(reply) + 32, reply_size,
                        ctypes.addressof(memory) + 32, len(table))
        status, value, after_table = oracle(raw, table, reply_size)
        assert bytes(request) == before_req, "request modified"
        assert bytes(memory)[:32] == b"\xc7" * 32, "left guard overwritten"
        assert bytes(memory)[32 + len(table):32 + len(table) + 32] == b"\xc7" * 32, "right guard overwritten"
        assert bytes(memory)[32:32 + len(table)] == after_table, "unexpected page-table mutation"
        assert bytes(reply)[:32] == b"\xb6" * 32, "reply left guard overwritten"
        assert bytes(reply)[32 + reply_size:32 + reply_size + 32] == b"\xb6" * 32, "reply right guard overwritten"
        assert result == status, ("wrong native status", result, status, raw.hex())
        if reply_size < 16:
            assert bytes(reply) == before_reply
        else:
            assert struct.unpack_from("<2Q", reply, 32) == (status, value), "reply does not match oracle"
            assert bytes(reply)[48:32 + reply_size] == b"\xb6" * (reply_size - 16)
        counts["cases"] += 1
        counts["allowed" if status == 0 else "refused"] += 1

    # Explicit successful RW->RO with Accessed/Dirty/PAT/cache bits preserved;
    # replay of the old value must refuse with zero change.
    for i in range(800):
        slot = rng.choice([0, 1, 255, 256, 510, 511, rng.randrange(512)])
        old = NX | (rng.randrange(0x100,0x100000) * PAGE) | 3
        old |= rng.choice([0, 0x20, 0x40, 0x60, 0x80, 0x8, 0x10, 0x800, 0x800 | 0x60])
        if i % 5 == 0:
            old |= 4
        if i % 7 == 0 and not old & 4:
            old |= 256
        table = bytearray(rng.randbytes(PAGE))
        struct.pack_into("<Q", table, slot * 8, old)
        raw = pack(slot, old, old - 2)
        check(raw, bytes(table))
        downgraded = bytearray(table)
        struct.pack_into("<Q", downgraded, slot * 8, old - 2)
        check(raw, bytes(downgraded))

    # The source-level 64-bit expected-old comparison must preserve
    # software metadata 52..58 and reject unmodeled PKEY bits 59..62.
    for bit in range(52, 63):
        old = ((1 << 63) | 0x400003) | (1 << bit)
        new = old - 2
        page = bytearray(PAGE)
        struct.pack_into("<Q", page, 511 * 8, old)
        payload = pack(511, old, new)
        permitted = bit < 59
        assert oracle(payload, bytes(page))[0] == (0 if permitted else 6)
        check(payload, bytes(page))
        if permitted:
            stale = bytearray(page)
            struct.pack_into("<Q", stale, 511 * 8, new)
            assert oracle(payload, bytes(stale))[0] == 9
            check(payload, bytes(stale))

    # Mutation campaign varies present, NXE, PGE, RW, physical width, stale
    # old bytes, no-op requests, illegal upgrades and user/global aliasing.
    for i in range(2400):
        slot = rng.choice([0, 511, 512, MASK64, rng.randrange(512)])
        old = rng.choice([NX | 0x400003, NX | 0x400063, 0x400003,
                          NX | 0x400001, NX | 0x400007, NX | 0x400107,
                          NX | (1 << 52) | 0x400003, rng.getrandbits(64)])
        table = bytearray(rng.randbytes(PAGE))
        struct.pack_into("<Q", table, (slot % 512) * 8, old)
        expected = old if rng.randrange(4) else old ^ 0x20
        candidate = rng.choice([expected - 2 & MASK64, expected,
                                expected | 2, 0, rng.getrandbits(64)])
        caps = rng.choice([CAPS, 32 | NXE, 52 | NXE, 52 | PGE,
                           52, 31 | NXE, 53 | NXE, MASK64, 0])
        check(pack(slot, expected, candidate, caps), bytes(table))
    for malformed in [b"", b"\0" * 24, b"\0" * 31, b"\0" * 33]:
        check(malformed, bytes(PAGE))
    for size in [0, 1, 15, 16, 17, 32]:
        check(pack(0, NX | 0x400003, NX | 0x400001), bytes(PAGE), size)
    for size in [0, 1, 16, 4095, 4097, 8192]:
        check(pack(0, NX | 0x400003, NX | 0x400001), bytes(size))
    assert counts["allowed"] >= 600 and counts["refused"] >= 2000, counts
    return {**counts, "status": "PASS", "hardware_tlb_verified": False,
            "smp_atomicity_verified": False}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as exc:
            print("dishonest native HIA RW downgrader rejected:", str(exc)[:250])
            return
        raise SystemExit("dishonest RW downgrader unexpectedly passed")
    result = campaign(args.library)
    # Bind every passing native oracle report to its own operation and inputs.
    # A malicious candidate is never allowed to publish a passing report.
    result.update(
        schema="heptakernel.pt-native-downgrade.v1",
        operation="RW_TO_RO",
        source_sha256=hashlib.sha256(Path("src/x86_pt_write_protect.hepta").read_bytes()).hexdigest(),
        library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest(),
    )
    Path("build/x86-pt-write-protect-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print("native HIA RW downgrade:", result)

if __name__ == "__main__":
    main()
