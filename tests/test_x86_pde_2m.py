#!/usr/bin/env python3
"""Independent byte-array oracle for native HIA 2MiB PDE commit/removal.

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
PA_MASK = ((1 << 52) - 1) & ~((1 << 21) - 1)
ALLOWED = PA_MASK | 0x1fff | (0x7f << 52) | NX
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
    # Zero is a restricted removal request: the OLD entry must be a
    # structurally valid present 2MiB leaf. Never clear an arbitrary table
    # pointer or an already absent entry, even with a matching old word.
    if candidate == 0:
        phys = expected & PA_MASK
        if (not expected & 1 or not expected & 128 or
                expected & ~ALLOWED or phys >= 1 << width):
            return 6, 0, original
        if ((expected & NX and not caps & NXE) or
                (expected & (1 << 8) and not caps & PGE)):
            return 8, 0, original
        if slot >= 512:
            return 6, 0, original
        if struct.unpack_from("<Q", original, slot * 8)[0] != expected:
            return 9, 0, original
        updated = bytearray(original)
        struct.pack_into("<Q", updated, slot * 8, 0)
        return 0, 0, bytes(updated)
    present = bool(candidate & 1)
    huge = bool(candidate & 0x80)
    writable = bool(candidate & 2)
    user = bool(candidate & 4)
    global_page = bool(candidate & (1 << 8))
    nx = bool(candidate & NX)
    phys = candidate & PA_MASK
    if (candidate & ~ALLOWED or not present or not huge or
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
        rep = ctypes.create_string_buffer(b"\xb6" * (reply_size + 64))
        mem = ctypes.create_string_buffer(b"\xc7" * 32 + table + b"\xc7" * 32)
        original_input = bytes(inp)
        original_reply = bytes(rep)
        rv = native(ctypes.addressof(inp) + 32, len(raw),
                    ctypes.addressof(rep) + 32, reply_size,
                    ctypes.addressof(mem) + 32, len(table))
        expected_status, expected_value, expected_table = oracle(raw, table, reply_size)
        assert bytes(inp) == original_input, "request modified"
        assert bytes(mem)[:32] == b"\xc7" * 32, "before table guard modified"
        assert bytes(mem)[32 + len(table):32 + len(table) + 32] == b"\xc7" * 32, "after table guard modified"
        assert bytes(mem)[32:32 + len(table)] == expected_table, "unauthorized table write or failed commit"
        assert bytes(rep)[:32] == b"\xb6" * 32, "before reply guard modified"
        assert bytes(rep)[32 + reply_size:32 + reply_size + 32] == b"\xb6" * 32, "after reply guard modified"
        assert rv == expected_status, ("status", rv, expected_status, raw.hex())
        if reply_size < 16:
            assert bytes(rep) == original_reply, "short reply was modified"
        else:
            status, value = struct.unpack_from("<2Q", rep, 32)
            assert (status, value) == (expected_status, expected_value)
            assert bytes(rep)[48:32 + reply_size] == b"\xb6" * (reply_size - 16)
        count += 1
        positives += expected_status == 0
        denials += expected_status != 0

    # Distinct old state per case, with occupied and unoccupied neighboring
    # slots; the implementation may touch only the selected 8 bytes.
    rng = random.Random(0xA917C0DE)
    for slot in (0, 1, 127, 255, 256, 510, 511, 512, 513, MASK64):
        table = rng.randbytes(PAGE)
        old = struct.unpack_from("<Q", table, (slot % 512) * 8)[0]
        for pte in (0x8000000000600087, 0x8000000000600085,
                    0x8000000000400085, 0x8000000000600187,
                    0x400085, 0x600087, 0x600007,
                    0, MASK64, 1 << 52):
            for cap in (CAPS, 32 | NXE | PGE, 52, 31 | NXE, 52 | NXE):
                check(pack(slot, old, pte, cap), table)
        check(pack(slot, old ^ 1, 0x8000000000600087), table)

    for _ in range(1600):
        slot = rng.choice((0, 1, 255, 511, 512, MASK64, rng.randrange(512)))
        table = rng.randbytes(PAGE)
        old = struct.unpack_from("<Q", table, (slot % 512) * 8)[0]
        proposed = rng.choice((0x8000000000600087, 0x8000000000600085,
                               0x400085, 0x8000000000600187,
                               MASK64, rng.getrandbits(64)))
        caps = rng.choice((CAPS, 52 | NXE, 32 | NXE | PGE,
                           52 | PGE, 52, 64, 0, MASK64))
        expect = old if rng.randrange(4) else old ^ 1
        check(pack(slot, expect, proposed, caps), table)

    # Per-bit architecture admission: 2MiB PAT lives at bit 12,
    # not in the frame address; 59..62 are unsupported high-key bits.
    for bit in (*range(3, 7), *range(9, 13), *range(52, 63)):
        slot = (bit * 37) % 512
        table = bytearray(rng.randbytes(PAGE))
        old = 0x200081 | ((bit & 7) << 5)
        struct.pack_into("<Q", table, slot * 8, old)
        candidate = NX | 0x600081 | (1 << bit)
        expected_status = 6 if bit >= 59 else 0
        assert oracle(pack(slot, old, candidate), bytes(table))[0] == expected_status
        check(pack(slot, old, candidate), bytes(table))
        check(pack(slot, old ^ 1, candidate), bytes(table))

    # Bits 13..20 remain reserved regardless of PAT or software metadata.
    for bit in range(13, 21):
        candidate = NX | 0x600081 | (1 << 12) | (1 << bit) | (1 << 58)
        assert oracle(pack(0, 0, candidate), bytes(PAGE))[0] == 6
        check(pack(0, 0, candidate), bytes(PAGE))

    # Compound metadata and the complete 8-byte old-entry comparison.
    for i in range(192):
        slot = (i * 71) % 512
        table = bytearray(rng.randbytes(PAGE))
        old = 0x200081 | ((i & 31) << 5)
        struct.pack_into("<Q", table, slot * 8, old)
        low = (rng.getrandbits(4) << 3) | (rng.getrandbits(4) << 9)
        software = rng.getrandbits(7) << 52
        candidate = NX | 0x600081 | low | software
        assert oracle(pack(slot, old, candidate), bytes(table))[0] == 0
        check(pack(slot, old, candidate), bytes(table))
        check(pack(slot, old ^ 1, candidate), bytes(table))

    # New admissions do not relax policy or capability checks.
    metadata = (1 << 12) | (1 << 9) | (1 << 52) | (1 << 58)
    for candidate, caps, status in (
        (0x600083 | metadata, CAPS, 6),
        (NX | 0x600185 | metadata, CAPS, 6),
        (NX | 0x600181 | metadata, 52 | NXE, 8),
        (NX | 0x600081 | metadata, 52 | PGE, 8),
        (NX | 0x600081 | metadata, CAPS, 0),
        (NX | 0x600081 | metadata | (1 << 20), CAPS, 6),
        (NX | 0x600081 | metadata | (1 << 59), CAPS, 6),
    ):
        assert oracle(pack(511, 0, candidate, caps), bytes(PAGE))[0] == status
        check(pack(511, 0, candidate, caps), bytes(PAGE))

    # Revoke existing 2MiB leaves; the exact original byte word cannot be
    # replayed after the native zero update. Neighbor bytes are random.
    for i in range(320):
        slot = rng.randrange(512)
        table = bytearray(rng.randbytes(PAGE))
        phys = rng.randrange(1, 1 << 30) << 21
        flags = rng.choice((0, 0x20, 0x40, 0x100, 0x1000,
                            (1 << 52), (1 << 58), 0x160))
        old = NX | phys | 0x81 | flags
        struct.pack_into("<Q", table, slot * 8, old)
        request = pack(slot, old, 0)
        assert oracle(request, bytes(table))[0] == 0
        check(request, bytes(table))
        struct.pack_into("<Q", table, slot * 8, 0)
        assert oracle(request, bytes(table))[0] == 9
        check(request, bytes(table))

    # A non-leaf, absent, reserved-bit, or CPU-incompatible OLD PDE must
    # not be removed. Capability errors remain distinct from bad entries.
    for old, caps, expected_status in (
        ((1 << 21) | 1, CAPS, 6),                 # not a huge leaf
        ((1 << 21) | 128, CAPS, 6),               # not present
        ((1 << 21) | 0x81 | (1 << 13), CAPS, 6),  # reserved physical bit
        ((1 << 21) | 0x81 | (1 << 61), CAPS, 6),  # unsupported PK
        ((1 << 40) | 0x81, 32 | NXE | PGE, 6),    # too wide
        (NX | (1 << 21) | 0x81, CAPS & ~NXE, 8),
        ((1 << 21) | 0x181, CAPS & ~PGE, 8),
    ):
        table = bytearray(PAGE)
        struct.pack_into("<Q", table, 0, old)
        request = pack(0, old, 0, caps)
        assert oracle(request, bytes(table))[0] == expected_status
        check(request, bytes(table))

    # Nonzero commits retain their original checks, including no W+X.
    assert oracle(pack(0, 0, 0), bytes(PAGE))[0] == 6
    assert oracle(pack(0, 0, NX | 0x200083), bytes(PAGE))[0] == 6

    seed = bytes(PAGE)
    for raw in (b"", b"\0" * 24, b"\0" * 31,
                b"\0" * 33, pack(0, 0, 0x8000000000600087) + b"\0"):
        check(raw, seed)
    for length in (0, 1, 15, 16, 17, 31, 32):
        check(pack(0, 0, 0x8000000000600087), seed, reply_size=length)
    for size in (0, 1, 16, 4088, 4095, 4097, 8192):
        check(pack(0, 0, 0x8000000000600087), bytes(size))
    assert positives >= 100 and denials >= 100
    return {"schema": "heptakernel.x86-pde-2m.v1", "status": "PASS", "cases": count, "commits": positives,
            "refusals": denials, "huge_page_pde": True,
            "concurrent_linearizability_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as exc:
            print("dishonest native HIA 2MiB PDE commit rejected:", str(exc)[:300])
            return
        raise SystemExit("dishonest 2MiB PDE committer unexpectedly passed oracle")
    report = campaign(args.library)
    Path("build/x86-pde-2m-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("native HIA 2MiB PDE commit:", report)


if __name__ == "__main__":
    main()
