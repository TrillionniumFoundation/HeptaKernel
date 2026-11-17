#!/usr/bin/env python3
"""Independent x86-64 #PF record oracle for native HIA admission.

This tests classification of captured faults. The exception entry, CRx/MSR
sampling and return path remain explicitly outside HIA in this tranche.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

MASK = (1 << 64) - 1
PAGE = 4096
NX = 1 << 63
PA_MASK = ((1 << 52) - 1) & ~4095
NXE = 1 << 11
WP = 1 << 16
ADDR = 0x400000
PTE_RO = NX | ADDR | 1
PTE_RW = PTE_RO | 2
NX_RIP = ADDR
WP_RIP = 0x123450


def sample(kind: int = 1):
    return (kind, 0x11 if kind == 1 else 3, ADDR,
            NX_RIP if kind == 1 else WP_RIP, ADDR,
            NX_RIP if kind == 1 else WP_RIP,
            PTE_RW if kind == 1 else PTE_RO, WP, NXE)


def pack(fields):
    return struct.pack("<9Q", *fields)


def oracle(raw: bytes, capacity: int = 16):
    if capacity < 16:
        return 1, None
    if len(raw) != 72:
        return 2, 0
    kind, error, cr2, rip, expected_addr, expected_rip, pte, cr0, efer = struct.unpack("<9Q", raw)
    if kind not in (1, 2):
        return 6, 0
    if (cr2 != expected_addr or rip != expected_rip or
            expected_rip == 0 or expected_addr & 4095 or
            pte & PA_MASK != expected_addr or not pte & 1 or pte & 4):
        return 7, 0
    if kind == 1:
        if error != 17 or not pte & NX:
            return 7, 0
        if not efer & NXE:
            return 8, 0
    else:
        if error != 3 or pte & 2:
            return 7, 0
        if not cr0 & WP:
            return 8, 0
    return 0, kind


def campaign(library: Path):
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    cases = 0
    positives = 0
    refusals = 0

    def check(raw: bytes, reply_size: int = 16):
        nonlocal cases, positives, refusals
        inp = ctypes.create_string_buffer(b"R" * 32 + raw + b"R" * 32)
        rep = ctypes.create_string_buffer(b"S" * (reply_size + 64))
        other = ctypes.create_string_buffer(b"T" * 32)
        original_in = bytes(inp)
        original_other = bytes(other)
        result = native(ctypes.addressof(inp) + 32, len(raw),
                        ctypes.addressof(rep) + 32, reply_size,
                        ctypes.addressof(other), len(other))
        status, value = oracle(raw, reply_size)
        assert result == status, ("return", result, status, raw.hex())
        assert bytes(inp) == original_in, "input mutated"
        assert bytes(other) == original_other, "unused mutable buffer mutated"
        assert bytes(rep)[:32] == b"S" * 32, "reply prefix overwritten"
        assert bytes(rep)[32 + reply_size:] == b"S" * 32, "reply suffix overwritten"
        if reply_size < 16:
            assert bytes(rep) == b"S" * (reply_size + 64), "short reply mutated"
        else:
            assert struct.unpack_from("<2Q", rep, 32) == (status, value), "reply differs"
            assert bytes(rep)[48:32 + reply_size] == b"S" * (reply_size - 16)
        cases += 1
        positives += status == 0
        refusals += status != 0

    for kind in (1, 2):
        original = sample(kind)
        check(pack(original))
        for field in range(9):
            for mutation in (0, 1, MASK, 0x11, 3, ADDR, NX, WP, NXE, PTE_RO, PTE_RW):
                altered = list(original)
                altered[field] = mutation
                check(pack(altered))
        # Hardware is allowed to update the accessed and dirty PTE bits.
        changed = list(original)
        changed[6] |= (1 << 5) | (1 << 6)
        check(pack(changed))
    for length in (0, 1, 16, 64, 71, 73, 80):
        check(bytes(length))
    for capacity in (0, 1, 7, 15, 16, 17, 32):
        check(pack(sample()), capacity)
    rng = random.Random(0x41F072)
    for index in range(2400):
        kind = rng.choice((1, 2))
        record = list(sample(kind))
        if index % 5:
            for _ in range(rng.randrange(1, 4)):
                k = rng.randrange(9)
                record[k] = rng.choice((0, 1, MASK, rng.getrandbits(64),
                                        ADDR, NX, WP, NXE, 3, 17, PTE_RW, PTE_RO))
        elif index % 2:
            record[6] |= 0x60
        check(pack(record))
    assert positives >= 200 and refusals >= 100
    return {"status": "PASS", "cases": cases, "accepted": positives,
            "refused": refusals, "native_exception_entry_verified": False,
            "smp_verified": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--expect-unsafe", action="store_true")
    args = ap.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as exc:
            print("dishonest native HIA fault gate rejected:", str(exc)[:250])
            return
        raise SystemExit("dishonest fault gate unexpectedly passed")
    result = campaign(args.library)
    Path("build/x86-pf-gate-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print("native HIA x86 #PF admission:", result)


if __name__ == "__main__":
    main()
