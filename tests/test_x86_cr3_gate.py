#!/usr/bin/env python3
"""Independent CR3 state-admission oracle for actual native HIA Core v8 bytes.

Does not read hardware CRx, execute MOV CR3, grant address-space ownership,
validate PML4 page contents, synchronize TLB/SMP, or implement Linux paging.
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
CR0_MODE = (1 << 31) | 1
CR4_PAE = 1 << 5
EFER_LONG = (1 << 8) | (1 << 10)
CR4_UNSUPPORTED = (1 << 12) | (1 << 17)
LOW_ALLOWED = (1 << 3) | (1 << 4)


def independent_oracle(candidate, cr0, cr4, efer, bits):
    if bits < 32 or bits > 52:
        return 1
    if (cr0 & CR0_MODE) != CR0_MODE or not (cr4 & CR4_PAE) or (
            efer & EFER_LONG) != EFER_LONG:
        return 2
    if cr4 & CR4_UNSUPPORTED:
        return 3
    if (candidate & 0xfff) & ~LOW_ALLOWED or not (candidate & ~0xfff) or (
            candidate >= (1 << bits)):
        return 4
    return 0


def compare_text(object_file, library):
    with tempfile.TemporaryDirectory(prefix="cr3-hia-byte-") as directory:
        hashes = []
        for index, source in enumerate((object_file, library)):
            out = Path(directory) / str(index)
            subprocess.run(
                ["objcopy", "--only-section=.text", "-O", "binary",
                 str(source.resolve()), str(out)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            raw = out.read_bytes()
            assert raw, "empty native HIA text section"
            hashes.append(hashlib.sha256(raw).hexdigest())
        assert hashes[0] == hashes[1], "host ELF changed the HIA native .text"
        return hashes[0]


def campaign(library, object_file=None):
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_uint64] * 5
    native.restype = ctypes.c_uint32
    checked = accepted = refused = 0

    def case(candidate, cr0, cr4, efer, bits):
        nonlocal checked, accepted, refused
        arguments = (candidate, cr0, cr4, efer, bits)
        expected = independent_oracle(*arguments)
        actual = native(*arguments)
        assert actual == expected, (arguments, expected, actual)
        checked += 1
        accepted += expected == 0
        refused += expected != 0

    rng = random.Random(0xC3A017)
    valid_cr0 = CR0_MODE | (1 << 16)
    valid_cr4 = CR4_PAE | (1 << 7)
    valid_efer = EFER_LONG | (1 << 11)
    widths = (32, 36, 40, 48, 52)
    flags = (0, 8, 16, 24)
    for bits in widths:
        for flag in flags:
            for base in (0x1000, 0x2000, 0x400000, (1 << (bits - 1)) & ~4095):
                case(base | flag, valid_cr0, valid_cr4, valid_efer, bits)
                case(base | flag, valid_cr0 & ~(1 << 31), valid_cr4, valid_efer, bits)
                case(base | flag, valid_cr0, valid_cr4 | (1 << 17), valid_efer, bits)
                case(base | flag, valid_cr0, valid_cr4 | (1 << 12), valid_efer, bits)
                case(base | flag, valid_cr0, valid_cr4, valid_efer & ~(1 << 10), bits)
                case(base | flag, valid_cr0, valid_cr4, valid_efer, 31)
                case(base | flag, valid_cr0, valid_cr4, valid_efer, 53)
                case(base | flag | 1, valid_cr0, valid_cr4, valid_efer, bits)
                case(base | flag | 0x100, valid_cr0, valid_cr4, valid_efer, bits)
                case(base | flag | (1 << 63), valid_cr0, valid_cr4, valid_efer, bits)
        case(0, valid_cr0, valid_cr4, valid_efer, bits)
        case(24, valid_cr0, valid_cr4, valid_efer, bits)
        case(1 << bits, valid_cr0, valid_cr4, valid_efer, bits)

    for _ in range(4200):
        bits = rng.choice(widths + (0, 31, 53, 64, MASK64))
        base = (rng.getrandbits(64) & ~0xfff) if rng.randrange(3) else (
            (rng.randrange(1, 1 << (min(bits, 52) - 12)) << 12)
            if 32 <= bits <= 52 else 0x1000)
        candidate = (base | rng.choice(flags + (1, 2, 32, 128, 2048))) & MASK64
        cr0 = valid_cr0 if rng.randrange(4) else rng.getrandbits(64)
        cr4 = valid_cr4 if rng.randrange(4) else rng.getrandbits(64)
        efer = valid_efer if rng.randrange(4) else rng.getrandbits(64)
        case(candidate, cr0, cr4, efer, bits)
    assert accepted >= 80 and refused >= 1000, (accepted, refused)
    report = {
        "schema": "heptakernel.hia-cr3-admission.v1",
        "status": "PASS",
        "cases": checked, "admitted": accepted, "refused": refused,
        "native_hia": True, "privileged_cr3_execution": False,
        "snapshot_authenticated": False, "cpu_and_tlb_state_changed": False,
        "linux_full_acceptance": "HOLD",
    }
    if object_file is not None:
        report["object_shared_text_sha256"] = compare_text(object_file, library)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    options = parser.parse_args()
    if options.expect_unsafe:
        native = ctypes.CDLL(str(options.library.resolve())).f0
        native.argtypes = [ctypes.c_uint64] * 5
        native.restype = ctypes.c_uint32
        unsafe = native(0, CR0_MODE, CR4_PAE, EFER_LONG, 52)
        assert independent_oracle(0, CR0_MODE, CR4_PAE, EFER_LONG, 52) == 4
        assert unsafe != 4, "dishonest HIA control escaped independent oracle"
        print("dishonest native HIA unconditional-admission control: REJECTED")
        return
    report = campaign(options.library, options.object)
    Path("build/x86-cr3-gate-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Native HIA CR3 admission:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
