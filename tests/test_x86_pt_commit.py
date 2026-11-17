#!/usr/bin/env python3
"""Independent byte-array oracle for the native HIA 4KiB PTE commit.

Models an exclusive, quiescent, caller-owned page table, not an atomic
compare-and-swap, TLB shootdown, physical ownership, or full Linux MMU.
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
PA_MASK = ((1 << 52) - 1) & ~(PAGE - 1)
ALLOWED = PA_MASK | 0x107 | NX
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
    present = bool(candidate & 1)
    writable = bool(candidate & 2)
    user = bool(candidate & 4)
    global_page = bool(candidate & (1 << 8))
    nx = bool(candidate & NX)
    phys = candidate & PA_MASK
    if (candidate & ~ALLOWED or not present or
            writable and not nx or user and global_page or
            phys >= 1 << width):
        return 6, 0, original
    if (nx and not caps & NXE) or (global_page and not caps & PGE):
        return 8, 0, original
    if slot >= 512:
        return 6, 0, original
    if struct.unpack_from("<Q", original, slot * 8)[0] != expected:
        return 9, 0, original
    updated = bytearray(original)
    struct.pack_into("<Q", updated, slot * 8, candidate)
    return 0, candidate, bytes(updated)


def pack(slot: int, expected: int, candidate: int, caps: int = CAPS):
    return struct.pack("<4Q", slot, expected, candidate, caps)


def campaign(library: Path):
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    count = 0
    positives = 0
    denials = 0

    def check(raw: bytes, table: bytes, reply_size: int = 16):
        nonlocal count, positives, denials
        inp = ctypes.create_string_buffer(b"\xa5" * 32 + raw + b"\xa5" * 32)
        rep = ctypes.create_string_buffer(b"\\xb6" * (reply_size + 64))
        mem = ctypes.create_string_buffer(b"\\xc7" * 32 + table + b"\\xc7" * 32)
        original_input = bytes(inp)
        original_reply = bytes(rep)
        rv = native(ctypes.addressof(inp) + 32, len(raw),
                    ctypes.addressof(rep) + 32, reply_size,
                    ctypes.addressof(mem) + 32, len(table))
        expected_status, expected_value, expected_table = oracle(raw, table, reply_size)
        assert bytes(inp) == original_input, "request modified"
        assert bytes(mem)[:32] == b"\\xc7" * 32, "before table guard modified"
        assert bytes(mem)[32 + len(table):32 + len(table) + 32] == b"\\xc7" * 32, "after table guard modified"
        assert bytes(mem)[32:32 + len(table)] == expected_table, "unauthorized table write or failed commit"
        assert bytes(rep)[:32] == b"\\xb6" * 32, "before reply guard modified"
        assert bytes(rep)[32 + reply_size:32 + reply_size + 32] == b"\\xb6" * 32, "after reply guard modified"
        assert rv == expected_status, ("status", rv, expected_status, raw.hex())
        if reply_size < 16:
            assert bytes(rep) == original_reply, "short reply was modified"
        else:
            status, value = struct.unpack_from("<2Q", rep, 32)
            assert (status, value) == (expected_status, expected_value)
            assert bytes(rep)[48:32 + reply_size] == b"\\xb6" * (reply_size - 16)
        count += 1
        positives += expected_status == 0
        denials += expected_status != 0

    # Distinct old state per case, with occupied and unoccupied neighboring
    # slots; the implementation may touch only the selected 8 bytes.
    rng = random.Random(0xA917C0DE)
    for slot in (0, 1, 127, 255, 256, 510, 511, 512, 513, MASK64):
        table = rng.randbytes(PAGE)
        old = struct.unpack_from("<Q", table, (slot % 512) * 8)[0]
        for pte in (0x8000000000400001, 0x8000000000400003,
                    0x8000000000400103, 0x8000000000400005,
                    0x400001, 0x400003, 0x8000000000400007,
                    0, MASK64, 1 << 52):
            for cap in (CAPS, 32 | NXE | PGE, 52, 31 | NXE, 52 | NXE):
                check(pack(slot, old, pte, cap), table)
        check(pack(slot, old ^ 1, 0x8000000000400003), table)

    for _ in range(1600):
        slot = rng.choice((0, 1, 255, 511, 512, MASK64, rng.randrange(512)))
        table = rng.randbytes(PAGE)
        old = struct.unpack_from("<Q", table, (slot % 512) * 8)[0]
        proposed = rng.choice((0x8000000000400003, 0x8000000000400001,
                               0x400001, 0x8000000000400103,
                               MASK64, rng.getrandbits(64)))
        caps = rng.choice((CAPS, 52 | NXE, 32 | NXE | PGE,
                           52 | PGE, 52, 64, 0, MASK64))
        expect = old if rng.randrange(4) else old ^ 1
        check(pack(slot, expect, proposed, caps), table)

    seed = bytes(PAGE)
    for raw in (b"", b"\\0" * 24, b"\\0" * 31,
                b"\\0" * 33, pack(0, 0, 0x8000000000400003) + b"\\0"):
        check(raw, seed)
    for length in (0, 1, 15, 16, 17, 31, 32):
        check(pack(0, 0, 0x8000000000400003), seed, reply_size=length)
    for size in (0, 1, 16, 4088, 4095, 4097, 8192):
        check(pack(0, 0, 0x8000000000400003), bytes(size))
    assert positives >= 100 and denials >= 100
    return {"status": "PASS", "cases": count, "commits": positives,
            "refusals": denials, "concurrent_linearizability_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as exc:
            print("dishonest native HIA PTE commit rejected:", str(exc)[:300])
            return
        raise SystemExit("dishonest PTE committer unexpectedly passed oracle")
    report = campaign(args.library)
    Path("build/x86-pt-commit-report.json").write_text(json.dumps(report, indent=2) + "\\n")
    print("native HIA PTE commit:", report)


if __name__ == "__main__":
    main()
