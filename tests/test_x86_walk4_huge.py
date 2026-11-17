#!/usr/bin/env python3
"""Independent supplied-entry x86-64 2MiB / 1GiB native-HIA oracle.

The inputs are caller-provided values, not read from actual CR3 or physical
RAM. Requires externally qualified EFER.NXE and 1GiB CPUID capability.
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

SUCCESS = 1 << 63
W = 1 << 62
U = 1 << 61
X = 1 << 60
MASK64 = (1 << 64) - 1


def independent_oracle(va, l4, l3, l2, bits, shift):
    if not 32 <= bits <= 52 or shift not in (21, 30):
        return 0
    top = va >> 48
    if top != (0xffff if (va & (1 << 47)) else 0):
        return 0
    if not (l4 & 1) or (l4 & (0x180 | 0x7ff0000000000000)):
        return 0
    root = l4 & (((1 << 52) - 1) & ~0xfff)
    if not root or root >= (1 << bits):
        return 0
    if not (l3 & 1) or l3 & 0x7ff0000000000000:
        return 0
    if shift == 21:
        if l3 & 0x180:
            return 0
        pd = l3 & (((1 << 52) - 1) & ~0xfff)
        if not pd or pd >= (1 << bits):
            return 0
        leaf = l2
        if not (leaf & 1) or not (leaf & (1 << 7)):
            return 0
        entries = (l4, l3, leaf)
    else:
        leaf = l3
        if not (leaf & (1 << 7)):
            return 0
        entries = (l4, leaf)  # the PDE is not traversed for a 1GiB leaf
    if leaf & 0x7ff0000000000000:
        return 0
    # In a large leaf bit 12 is PAT; bits 13..shift-1 are reserved.
    if leaf & sum(1 << i for i in range(13, shift)):
        return 0
    base = (leaf & ((1 << 52) - 1)) & ~((1 << shift) - 1)
    if base >= (1 << bits):
        return 0
    pa = base | (va & ((1 << shift) - 1))
    return (SUCCESS | pa | (W if all(e & 2 for e in entries) else 0)
            | (U if all(e & 4 for e in entries) else 0)
            | (X if all(not (e & SUCCESS) for e in entries) else 0))


def text_identity(object_file: Path, library: Path):
    with tempfile.TemporaryDirectory(prefix="hia-huge-byte-") as folder:
        hashes = []
        for i, source in enumerate((object_file, library)):
            output = Path(folder) / str(i)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(source.resolve()), str(output)], check=True,
                           capture_output=True)
            raw = output.read_bytes()
            assert raw, "empty native machine code section"
            hashes.append(hashlib.sha256(raw).hexdigest())
        assert hashes[0] == hashes[1], "HIA .text changed during host linking"
        return hashes[0]


def campaign(library: Path, object_file: Path | None):
    native = ctypes.CDLL(str(library.resolve())).walk4_huge
    native.argtypes = [ctypes.c_uint64] * 6
    native.restype = ctypes.c_uint64
    counts = dict(cases=0, admitted=0, denied=0, large_2m=0, large_1g=0)
    rng = random.Random(0xA1172026)

    def check(values):
        expected = independent_oracle(*values)
        actual = native(*values)
        assert actual == expected, (tuple(hex(v) for v in values),
                                    hex(expected), hex(actual))
        counts["cases"] += 1
        counts["admitted" if expected else "denied"] += 1
        if expected:
            counts["large_2m" if values[-1] == 21 else "large_1g"] += 1

    flags = (1, 3, 5, 7, 0x107, 0x8000000000000007)
    addresses = (0, 0x1fff, 0x12345678, 0x7fffffffffff,
                 0xffff800000000000, 0xffffffffffffffff)
    for bits in (32, 36, 40, 48, 52):
        for shift in (21, 30):
            for va in addresses:
                for f in flags:
                    for phys in (0, 1 << shift, 1 << (bits - 1)):
                        l4 = 0x1000 | f
                        l3 = ((phys | 0x80 | f) if shift == 30 else (0x2000 | f))
                        l2 = ((phys | 0x80 | f) if shift == 21 else MASK64)
                        check((va, l4, l3, l2, bits, shift))
                        for slot, bad_mask in ((1, 0x80), (1, 1 << 52),
                                                (2, 1 << 60),
                                                (3 if shift == 21 else 2, 1 << 13)):
                            altered = [va, l4, l3, l2, bits, shift]
                            altered[slot] |= bad_mask
                            check(tuple(altered))
    for shift in (21, 30):
        base = (0x123, 0x1007, (0x2087 if shift == 30 else 0x2007),
                (0 if shift == 30 else 0x400087), 52, shift)
        for field in range(6):
            for bit in (0, 1, 7, 8, 12, 13, 20, 21, 29, 30, 47, 52, 60, 63):
                altered = list(base)
                altered[field] ^= 1 << bit
                check(tuple(altered))
    for _ in range(5500):
        bits = rng.choice((0, 31, 32, 36, 40, 48, 52, 53, 64))
        shift = rng.choice((0, 12, 21, 30, 31, 63))
        va = rng.getrandbits(64)
        l4, l3, l2 = (rng.getrandbits(64) for _ in range(3))
        check((va, l4, l3, l2, bits, shift))
    assert counts["large_2m"] >= 100 and counts["large_1g"] >= 100, counts
    assert counts["denied"] >= 1000, counts
    report = {
        "schema": "heptakernel.hia-supplied-huge-entries.v1",
        "status": "PASS", **counts, "native_hia": True,
        "leaf_sizes": [2097152, 1073741824],
        "physical_tables_authenticated": False,
        "cpuid_1g_and_nxe_checked_here": False,
        "hardware_cr3_or_tlb_access": False,
        "linux_full_acceptance": "HOLD",
    }
    if object_file is not None:
        report["object_shared_text_sha256"] = text_identity(object_file, library)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    options = parser.parse_args()
    if options.expect_unsafe:
        native = ctypes.CDLL(str(options.library.resolve())).walk4_huge
        native.argtypes = [ctypes.c_uint64] * 6
        native.restype = ctypes.c_uint64
        invalid = (0, 0, 0, 0, 52, 21)
        assert independent_oracle(*invalid) == 0
        assert native(*invalid) != 0, "dishonest HIA escaped independent oracle"
        print("Dishonest HIA huge-leaf policy: REJECTED")
        return
    report = campaign(options.library, options.object)
    Path("build/x86-walk4-huge-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("HIA native supplied-entry huge-leaf policy:", json.dumps(report))


if __name__ == "__main__":
    main()
