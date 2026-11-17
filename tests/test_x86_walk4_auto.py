#!/usr/bin/env python3
"""Independent oracle for native HIA indexed four-level supplied table pages.

Caller-supplied 16 KiB snapshots, not hardware/owned physical memory. The
metadata binds physical parent-link identities to supplied pages, but does
not authenticate their provenance, synchronize CPUs or touch CR3/TLB.
"""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import random
import struct

from test_x86_walk4_entries import independent_oracle as oracle_4k, compare_text
from test_x86_walk4_huge import independent_oracle as oracle_huge

PAGE = 4096
TOTAL = PAGE * 4
PHYS_MASK = ((1 << 52) - 1) & ~4095
MASK64 = (1 << 64) - 1


def oracle(request: bytes, tables: bytes, reply_size: int):
    if reply_size < 16:
        return 1, None
    if len(request) != 48:
        return 2, 0
    if len(tables) != TOTAL:
        return 3, 0
    va, bits, cr3, l3, l2, l1 = struct.unpack("<6Q", request)
    if not 32 <= bits <= 52:
        return 4, 0
    roots = (cr3, l3, l2, l1)
    if (cr3 & 4095) & ~24 or any(x & 4095 for x in roots[1:]):
        return 4, 0
    if any((x & PHYS_MASK) == 0 or x >= 1 << bits for x in roots):
        return 4, 0
    indexes = tuple((va >> shift) & 511 for shift in (39, 30, 21, 12))
    entries = tuple(struct.unpack_from("<Q", tables, level * PAGE + idx * 8)[0]
                    for level, idx in enumerate(indexes))
    # First encountered PS leaf wins. No access/link obligation below a huge leaf.
    shift = 30 if entries[1] & 128 else 21 if entries[2] & 128 else 12
    active_links = {30: 1, 21: 2, 12: 3}[shift]
    if any((entries[level] & PHYS_MASK) != roots[level + 1]
           for level in range(active_links)):
        return 5, 0
    translated = (oracle_4k(va, *entries, bits) if shift == 12 else
                  oracle_huge(va, entries[0], entries[1], entries[2], bits, shift))
    return (0, translated) if translated else (6, 0)


def fixture(rng, va, *, bits=52, cr3=0x2000, l3=0x3000, l2=0x4000, l1=0x5000,
            entries=None):
    data = bytearray(rng.randbytes(TOTAL))
    actual_entries = entries if entries is not None else (
        l3 | 7, l2 | 7, l1 | 7, 0x8000000000006007)
    indexes = ((va >> 39) & 511, (va >> 30) & 511,
               (va >> 21) & 511, (va >> 12) & 511)
    for level, (idx, entry) in enumerate(zip(indexes, actual_entries)):
        struct.pack_into("<Q", data, level * PAGE + idx * 8, entry)
    return struct.pack("<6Q", va, bits, cr3, l3, l2, l1), bytes(data)


def campaign(library: Path, object_file=None):
    fn = ctypes.CDLL(str(library.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    rng = random.Random(0x4A97DE)
    counts = dict(cases=0, accepted=0, refused=0,
                  admitted_4k=0, admitted_2m=0, admitted_1g=0)

    def check(request, tables, reply_size=16):
        expected_status, expected_result = oracle(request, tables, reply_size)
        inp = ctypes.create_string_buffer(b"\xa5" * 32 + request + b"\xa5" * 32)
        mem = ctypes.create_string_buffer(b"\xc7" * 32 + tables + b"\xc7" * 32)
        rep = ctypes.create_string_buffer(b"\xb6" * (32 + reply_size + 32))
        original_in = bytes(inp)
        original_mem = bytes(mem)
        original_reply = bytes(rep)
        status = fn(ctypes.addressof(inp) + 32, len(request),
                    ctypes.addressof(rep) + 32, reply_size,
                    ctypes.addressof(mem) + 32, len(tables))
        assert status == expected_status, ("status", status, expected_status)
        assert bytes(inp) == original_in, "request modified"
        assert bytes(mem) == original_mem, "table snapshot modified"
        actual_reply = bytes(rep)
        assert actual_reply[:32] == b"\xb6" * 32
        assert actual_reply[32 + reply_size:32 + reply_size + 32] == b"\xb6" * 32
        if reply_size < 16:
            assert actual_reply == original_reply, "short reply changed"
        else:
            actual_status, value = struct.unpack_from("<2Q", actual_reply, 32)
            assert (actual_status, value) == (expected_status, expected_result)
            assert actual_reply[48:32 + reply_size] == b"\xb6" * (reply_size - 16)
        counts["cases"] += 1
        counts["accepted" if expected_status == 0 else "refused"] += 1
        if expected_status == 0:
            va = struct.unpack_from("<Q", request)[0]
            i3 = (va >> 30) & 511
            i2 = (va >> 21) & 511
            l3 = struct.unpack_from("<Q", tables, PAGE + 8 * i3)[0]
            l2 = struct.unpack_from("<Q", tables, 2 * PAGE + 8 * i2)[0]
            counts["admitted_1g" if l3 & 128 else
                   "admitted_2m" if l2 & 128 else "admitted_4k"] += 1

    vas = (0, 0x123, 0xfff, 0x1000, 0x7fffffffffff,
           0xffff800000000000, 0xffffffffffffffff,
           0x0000800000000000, 0xffff7fffffffffff)
    for va in vas:
        for bits in (32, 36, 48, 52):
            req, tables = fixture(rng, va, bits=bits)
            check(req, tables)
            for flags in (1, 3, 5, 7, 0x107, 0x8000000000000007, 0):
                entries = (0x3007, 0x4007, 0x5007, 0x6000 | flags)
                check(*fixture(rng, va, bits=bits, entries=entries))
            for level in range(3):
                items = [0x3007, 0x4007, 0x5007, 0x8000000000006007]
                items[level] = (0x7000 + level * 4096) | 7
                check(*fixture(rng, va, bits=bits, entries=items))
    for va in (0, 0x7fffffffffff, 0xffff800000000000):
        for bad in (0, 31, 53, 64, MASK64):
            check(*fixture(rng, va, bits=bad))
        for root in (0, 1, 0x2001, 0x2fe7, 1 << 52, MASK64):
            check(*fixture(rng, va, cr3=root))
        for arg in ("l3", "l2", "l1"):
            for invalid in (0, 1, 0x3001, 0x100000000, 1 << 52):
                check(*fixture(rng, va, **{arg: invalid}))
    for _ in range(1600):
        va = rng.choice(vas + (rng.getrandbits(64),))
        bits = rng.choice((31, 32, 36, 48, 52, 53))
        req, snapshot = fixture(rng, va, bits=bits)
        if rng.randrange(4) == 0:
            raw = bytearray(req)
            pos = rng.choice((0, 1, 2, 3, 4, 5))
            struct.pack_into("<Q", raw, pos * 8, rng.getrandbits(64))
            req = bytes(raw)
        elif rng.randrange(3) == 0:
            mutable = bytearray(snapshot)
            level = rng.randrange(4)
            index = (va >> (39 - 9 * level)) & 511
            offset = level * PAGE + 8 * index
            old = struct.unpack_from("<Q", mutable, offset)[0]
            struct.pack_into("<Q", mutable, offset, old ^ (1 << rng.randrange(64)))
            snapshot = bytes(mutable)
        check(req, snapshot)
    # Real HIA path selects PS at the level where it is first encountered.
    # Untraversed descendants contain unrelated, possibly hostile entries.
    for mode in (21, 30):
        base_entries = ([0x3007, 0x4007, 0x200087, MASK64] if mode == 21 else
                        [0x3007, 0x40000087, MASK64, MASK64])
        leaf_level = 2 if mode == 21 else 1
        for va in vas:
            for bits in (32, 36, 48, 52):
                check(*fixture(rng, va, bits=bits, entries=base_entries))
                for bit in (0, 1, 2, 5, 12, 13, 21, 30, 52, 60, 63):
                    altered = list(base_entries)
                    altered[leaf_level] ^= 1 << bit
                    check(*fixture(rng, va, bits=bits, entries=altered))
                for parent in range(leaf_level):
                    altered = list(base_entries)
                    altered[parent] ^= 1 << 12
                    check(*fixture(rng, va, bits=bits, entries=altered))
    for mode in (21, 30):
        base_entries = ([0x3007, 0x4007, 0x200087, MASK64] if mode == 21 else
                        [0x3007, 0x40000087, MASK64, MASK64])
        for i in range(200):
            altered = list(base_entries)
            for level in range(4):
                if level > (1 if mode == 30 else 2):
                    altered[level] = rng.getrandbits(64)
            check(*fixture(rng, rng.choice(vas), entries=altered))
    request, tables = fixture(rng, 0x123)
    for malformed in (b"", b"\0" * 16, request[:-1], request + b"\0"):
        check(malformed, tables)
    for size in (0, 1, 4095, 4096, TOTAL - 1, TOTAL + 1):
        check(request, tables[:size] if size <= TOTAL else tables + b"\0")
    for size in (0, 1, 8, 15, 16, 17, 32):
        check(request, tables, size)
    assert counts["accepted"] > 100 and counts["refused"] > 200, counts
    assert all(counts[k] >= 60 for k in ("admitted_4k", "admitted_2m", "admitted_1g")), counts
    report = dict(schema="heptakernel.hia-indexed-mixed-leaf-snapshots.v1",
                  status="PASS", **counts, native_hia=True,
                  read_only_table_snapshot=True, authenticated_physical_tables=False,
                  hardware_cr3_walk=False, linux_full_acceptance="HOLD")
    if object_file is not None:
        report["object_shared_text_sha256"] = compare_text(object_file, library)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("library", type=Path)
    p.add_argument("--object", type=Path)
    p.add_argument("--expect-unsafe", action="store_true")
    args = p.parse_args()
    if args.expect_unsafe:
        fn = ctypes.CDLL(str(args.library.resolve())).f0
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        fn.restype = ctypes.c_uint32
        req = ctypes.create_string_buffer(1)
        reply = ctypes.create_string_buffer(16)
        pages = ctypes.create_string_buffer(TOTAL)
        status = fn(ctypes.addressof(req), 0, ctypes.addressof(reply), 16,
                    ctypes.addressof(pages), TOTAL)
        assert oracle(b"", bytes(TOTAL), 16)[0] == 2
        assert status == 0, "dishonest native HIA refusal control no longer dishonest"
        print("HIA dishonest auto leaf selection: REJECTED")
        return
    report = campaign(args.library, args.object)
    Path("build/x86-walk4-auto-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Native HIA indexed mixed-leaf snapshots:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
