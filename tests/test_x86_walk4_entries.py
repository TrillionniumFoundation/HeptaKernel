#!/usr/bin/env python3
"""Independent native HIA four-level *supplied-entry* policy oracle.

Entries are caller snapshots, not indexed/owned physical page-table pages.
No privileged CR3 load, MMU hardware walk, PCID, large page, TLB, SMP or
page ownership assertion is made. NX interpretation assumes EFER.NXE=1.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile

MASK64 = (1 << 64) - 1
PHYS_MASK = ((1 << 52) - 1) & ~4095
HIGH_RESERVED = 0x7ff0000000000000
SUCCESS = 1 << 63
RW_RESULT = 1 << 62
US_RESULT = 1 << 61
EX_RESULT = 1 << 60


def independent_oracle(va, pml4e, pdpte, pde, pte, bits):
    if not 32 <= bits <= 52:
        return 0
    sign = bool(va & (1 << 47))
    if (va >> 48) != (0xffff if sign else 0):
        return 0
    entries = (pml4e, pdpte, pde, pte)
    if any(not (entry & 1) or (entry & HIGH_RESERVED) for entry in entries):
        return 0
    if any(entry & (0x80 | 0x100) for entry in entries[:3]):
        return 0
    bases = tuple(entry & PHYS_MASK for entry in entries)
    if any(base == 0 for base in bases[:3]) or any(base >= (1 << bits) for base in bases):
        return 0
    writable = all(entry & 2 for entry in entries)
    user = all(entry & 4 for entry in entries)
    executable = not any(entry & SUCCESS for entry in entries)
    return (SUCCESS | bases[-1] | (va & 4095)
            | (RW_RESULT if writable else 0)
            | (US_RESULT if user else 0)
            | (EX_RESULT if executable else 0))


def compare_text(object_file, library):
    with tempfile.TemporaryDirectory(prefix="walk4-byte-") as folder:
        values = []
        for n, item in enumerate((object_file, library)):
            output = Path(folder) / str(n)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(item.resolve()), str(output)],
                           check=True, capture_output=True)
            raw = output.read_bytes()
            assert raw
            values.append(hashlib.sha256(raw).hexdigest())
        assert values[0] == values[1], "native HIA text changed after ELF linking"
        return values[0]


def campaign(library, object_file=None):
    fn = ctypes.CDLL(str(library.resolve())).walk4
    fn.argtypes = [ctypes.c_uint64] * 6
    fn.restype = ctypes.c_uint64
    rng = random.Random(0x4217)
    counts = dict(cases=0, valid=0, refused=0)

    def check(args):
        expected = independent_oracle(*args)
        actual = fn(*args)
        assert actual == expected, (tuple(hex(x) for x in args),
                                    hex(expected), hex(actual))
        counts["cases"] += 1
        counts["valid" if expected else "refused"] += 1

    parents = (0x2007, 0x3007, 0x4007)
    for bits in (32, 36, 40, 48, 52):
        for va in (0, 0x123, 0x7fffffffffff, 0xffff800000000000,
                   0xffffffffffffffff, 0x0000800000000000, 0xffff7fffffffffff):
            for flags in (1, 3, 5, 7, 0x107, 0x8000000000000007):
                check((va, *parents, (0x5000 | flags), bits))
        for low in range(256):
            for flag in (1, 3, 5, 7):
                check((0xffff800000000000 | low, parents[0], parents[1],
                       parents[2], ((1 << (bits - 1)) & PHYS_MASK) | flag, bits))
    for _ in range(5000):
        bits = rng.choice((0, 31, 32, 36, 40, 48, 52, 53, 64, MASK64))
        va = rng.choice((rng.getrandbits(64), rng.randrange(1 << 47),
                         (0xffff << 48) | rng.getrandbits(47)))
        entries = tuple(rng.choice((
            rng.getrandbits(64), rng.getrandbits(min(bits, 52)) & ~4095 | rng.randrange(4096),
            0, 3, 0x2007, 0x3007, 0x4007, 0x5007, (1 << 63) | 0x5001))
            for _ in range(4))
        check((va, *entries, bits))
    # Each admission branch is exercised, including reserved PS and NX.
    base = (0x123, *parents, 0x5007, 52)
    for pos in range(6):
        for bit in (0, 7, 8, 12, 20, 47, 51, 52, 60, 63):
            sample = list(base)
            sample[pos] ^= 1 << bit
            check(tuple(sample))
    for case in ((0, *parents, 0x5007, 52),
                 (0, *parents, 0x5003, 52),
                 (0, *parents, 0x5005, 52),
                 (0, *parents, 0x8000000000005007, 52),
                 (0, 0x2087, parents[1], parents[2], 0x5007, 52),
                 (0, 0x2007, 0x3087, parents[2], 0x5007, 52),
                 (0, 0x2007, 0x3007, 0x4087, 0x5007, 52)):
        check(case)
    assert counts["valid"] >= 900 and counts["refused"] >= 1000, counts
    report = {"schema": "heptakernel.hia-supplied-four-level-entries.v1",
              "status": "PASS", **counts, "actual_hia_native": True,
              "supplied_entries_only": True, "hardware_page_walk": False,
              "page_table_ownership_proved": False, "linux_full_acceptance": "HOLD"}
    if object_file is not None:
        report["object_shared_text_sha256"] = compare_text(object_file, library)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("library", type=Path)
    p.add_argument("--object", type=Path)
    p.add_argument("--expect-unsafe", action="store_true")
    opts = p.parse_args()
    if opts.expect_unsafe:
        fn = ctypes.CDLL(str(opts.library.resolve())).walk4
        fn.argtypes = [ctypes.c_uint64] * 6
        fn.restype = ctypes.c_uint64
        bad = (0, 0, 0, 0, 0, 52)
        assert independent_oracle(*bad) == 0
        assert fn(*bad) != 0, "dishonest HIA always-accept control escaped"
        print("HIA dishonest four-level admission: REJECTED")
        return
    report = campaign(opts.library, opts.object)
    Path("build/x86-walk4-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Native HIA supplied-entry four-level walk:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
