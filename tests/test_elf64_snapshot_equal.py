#!/usr/bin/env python3
"""Independent byte oracle for bounded native HIA ELF snapshot equality.

The reference is a separately provided buffer. This checks equality, not its
authenticity, lifetime, exclusion from DMA, or concurrent mutability.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import random
import struct
import subprocess
import tempfile
from pathlib import Path

MINIMUM, MAXIMUM, RECEIPT = 64, 1 << 20, 16


def native(path: Path):
    function = ctypes.CDLL(str(path.resolve())).f0
    function.argtypes = [ctypes.c_void_p, ctypes.c_size_t] * 3
    function.restype = ctypes.c_uint32
    return function


def oracle(ref: bytes, live: bytes, receipt_size: int) -> tuple[int, bytes | None]:
    if len(ref) != len(live):
        return 1, None
    if not MINIMUM <= len(ref) <= MAXIMUM:
        return 2, None
    if receipt_size != RECEIPT:
        return 3, None
    if ref != live:
        return 4, None
    return 0, b"\xa5\x5a" + b"\xe9" * 14


def experiment(library: Path, unsafe: bool) -> dict:
    f = native(library)
    rng = random.Random(0x20261121)
    counts: dict[int, int] = {}
    cases = differences = accepted = 0

    def check(ref: bytes, live: bytes, outlen: int = RECEIPT):
        nonlocal cases, differences, accepted
        buf_ref = ctypes.create_string_buffer(b"\x73" * 32 + ref + b"\x73" * 32)
        buf_live = ctypes.create_string_buffer(b"\x84" * 32 + live + b"\x84" * 32)
        out = ctypes.create_string_buffer(b"\x95" * 32 + b"\xe9" * outlen + b"\x95" * 32)
        before = (bytes(buf_ref), bytes(buf_live), bytes(out))
        result = f(ctypes.addressof(buf_ref) + 32, len(ref),
                   ctypes.addressof(buf_live) + 32, len(live),
                   ctypes.addressof(out) + 32, outlen)
        expected, receipt = oracle(ref, live, outlen)
        wanted = receipt if receipt is not None else b"\xe9" * outlen
        actual = bytes(out)[32:32 + outlen]
        mismatch = result != expected or actual != wanted
        cases += 1
        counts[expected] = counts.get(expected, 0) + 1
        accepted += (expected == 0)
        differences += mismatch
        if not unsafe:
            assert not mismatch, (cases, expected, result, wanted.hex(), actual.hex())
        assert bytes(buf_ref) == before[0], ("reference mutation", cases)
        assert bytes(buf_live) == before[1], ("candidate mutation", cases)
        assert bytes(out)[:32] == before[2][:32], ("left canary", cases)
        assert bytes(out)[32 + outlen:] == before[2][32 + outlen:], (
            "right canary", cases)

    for size in (0, 1, 63, 64, 65, 4095, 4096, 7292, 8192, 16384,
                 MAXIMUM, MAXIMUM + 1):
        ref = bytes(rng.randrange(256) for _ in range(size))
        check(ref, ref)
        if ref:
            altered = bytearray(ref)
            for i in (0, size // 2, size - 1):
                altered[i] ^= 0x5a
                check(ref, bytes(altered))
                altered[i] ^= 0x5a
            check(ref, ref[:-1])
            check(ref[:-1], ref)
    source = bytes(rng.randrange(256) for _ in range(7292))
    for out_size in (0, 1, 15, 16, 17, 24):
        check(source, source, out_size)
        altered = bytearray(source)
        altered[0x1200] ^= 0x7f
        check(source, bytes(altered), out_size)
    for _ in range(1000):
        size = rng.choice((64, 65, 128, 4096, 7292, 9000, 16384))
        ref = bytes(rng.randrange(256) for _ in range(size))
        mode = rng.randrange(5)
        if mode == 0:
            live = ref
        elif mode == 1:
            index = rng.randrange(size)
            live = ref[:index] + bytes([ref[index] ^ 0x80]) + ref[index + 1:]
        elif mode == 2:
            live = ref[:-1]
        elif mode == 3:
            live = ref + b"\x00"
        else:
            live = bytes(size)
        check(ref, live)
    assert cases >= 1000 and accepted >= 100
    if unsafe:
        assert differences >= 500, (cases, differences)
    else:
        assert differences == 0, (cases, differences)
        assert all(counts.get(s, 0) for s in range(5))
    return {
        "schema": "heptakernel.elf64-snapshot-equal.v1",
        "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
        "native_hia": True,
        "cases": cases,
        "accepted": accepted,
        "status_counts": counts,
        "oracle_divergences": differences,
        "full_acceptance": "HOLD",
        "reference_provenance_authenticated": False,
        "race_safe_or_atomic": False,
    }


def identity(obj: Path, lib: Path) -> str:
    with tempfile.TemporaryDirectory() as d:
        extracted = []
        for n, source in enumerate((obj, lib)):
            dest = Path(d) / f"{n}.bin"
            subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                            str(source.resolve()), str(dest)], check=True)
            extracted.append(dest.read_bytes())
        assert extracted[0] and extracted[0] == extracted[1]
        return hashlib.sha256(extracted[0]).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    report = experiment(args.library, args.expect_unsafe)
    if args.object:
        report["text_sha256"] = identity(args.object, args.library)
    print(json.dumps(report, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/elf64-snapshot-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
