#!/usr/bin/env python3
"""Independent byte-level PT_LOAD oracle for a restricted native HIA admission gate.

This checks only a bounded static segment-layout subset, not mapping, dynamic
relocations, process construction, a complete kernel, or Linux execve.
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

MAX_USER = 1 << 47
HDR, PHDR = 64, 56
LOAD, INTERP = 1, 3
READ, WRITE, EXEC = 4, 2, 1


def reference(image: bytes) -> int:
    if len(image) < HDR:
        return 1
    if image[:4] != b"\x7fELF":
        return 2
    if (image[4:7] != b"\x02\x01\x01" or image[7] not in (0, 3)
            or image[8:16] != bytes(8)):
        return 3
    kind, machine, version = struct.unpack_from("<HHI", image, 16)
    if kind not in (2, 3) or machine != 62 or version != 1:
        return 4
    ehsize, entsize, count = struct.unpack_from("<HHH", image, 52)
    if ehsize != HDR or entsize != PHDR or not 1 <= count <= 128:
        return 5
    entry = struct.unpack_from("<Q", image, 24)[0]
    if not 4096 <= entry < MAX_USER:
        return 7
    phoff = struct.unpack_from("<Q", image, 32)[0]
    if phoff < HDR or phoff > len(image) or phoff % 8:
        return 6
    if count * PHDR > len(image) - phoff:
        return 6

    has_load = has_entry = False
    for i in range(count):
        start = phoff + PHDR * i
        typ, flags, offset, va, _paddr, filesz, memsz, align = (
            struct.unpack_from("<IIQQQQQQ", image, start))
        if typ == INTERP:
            return 12
        if typ != LOAD:
            continue
        if flags & ~7 or (flags & WRITE and flags & EXEC):
            return 9
        if (memsz == 0 or filesz > memsz or not 4096 <= va < MAX_USER
                or memsz > MAX_USER - va
                or offset > len(image)
                or filesz > len(image) - offset):
            return 10
        if (offset & 4095) != (va & 4095):
            return 10
        if align > 1 and ((align & (align - 1)) or
                          ((offset & (align - 1)) != (va & (align - 1)))):
            return 10
        has_load = True
        if flags & EXEC and va <= entry < va + filesz:
            has_entry = True
    if not has_load:
        return 8
    return 0 if has_entry else 11


def example(*, kind: int = 2, phoff: int = 64,
            entries: tuple[tuple[int, int, int, int, int, int, int], ...]
            | None = None, entry: int = 0x401010) -> bytes:
    if entries is None:
        entries = ((LOAD, 5, 0x1000, 0x401000, 0x100, 0x200, 0x1000),
                   (LOAD, 6, 0x2000, 0x402000, 0x80, 0x100, 0x1000))
    end = max(HDR, phoff + PHDR * len(entries))
    for typ, flags, off, va, fs, ms, align in entries:
        if off <= 131072 and fs <= 16384:
            end = max(end, off + fs)
    image = bytearray(end)
    image[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into("<HHI", image, 16, kind, 62, 1)
    struct.pack_into("<Q", image, 24, entry)
    struct.pack_into("<Q", image, 32, phoff)
    struct.pack_into("<HHH", image, 52, HDR, PHDR, len(entries))
    for i, (typ, flags, off, va, fs, ms, align) in enumerate(entries):
        struct.pack_into("<IIQQQQQQ", image, phoff + PHDR * i,
                         typ, flags, off, va, 0, fs, ms, align)
    return bytes(image)


def mutate_ph(image: bytes, index: int, offset: int, fmt: str, value: int) -> bytes:
    b = bytearray(image)
    base = struct.unpack_from("<Q", b, 32)[0] + index * PHDR
    struct.pack_into(fmt, b, base + offset, value)
    return bytes(b)


def native_function(path: Path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    return f


def campaign(path: Path, unsafe: bool = False) -> dict:
    f = native_function(path)
    rng = random.Random(202611201425)
    cases = accepted = mismatches = 0
    status_counts: dict[int, int] = {}

    def check(image: bytes):
        nonlocal cases, accepted, mismatches
        inp = ctypes.create_string_buffer(b"\xa7" * 32 + image + b"\xa7" * 32)
        reply = ctypes.create_string_buffer(b"\xb8" * 128)
        scratch = ctypes.create_string_buffer(b"\xc9" * 128)
        old = (bytes(inp), bytes(reply), bytes(scratch))
        observed = f(ctypes.addressof(inp) + 32, len(image),
                     ctypes.addressof(reply) + 32, 64,
                     ctypes.addressof(scratch) + 32, 64)
        expected = reference(image)
        cases += 1
        accepted += expected == 0
        status_counts[expected] = status_counts.get(expected, 0) + 1
        mismatches += expected != observed
        if not unsafe:
            assert expected == observed, (
                "HIA versus independent oracle mismatch", cases, expected,
                observed, image[:64].hex())
        assert (bytes(inp), bytes(reply), bytes(scratch)) == old, (
            "input, output or canary changed", cases)

    good = example()
    check(good)
    for kind in (2, 3):
        for kind_flags in (5, 4, 1):
            for align in (0, 1, 4096, 8192):
                for phoff in (64, 128):
                    entry = 0x401010
                    check(example(kind=kind, phoff=phoff,
                                  entries=((LOAD, kind_flags, 0x2000,
                                            0x402000, 0x100, 0x200, align),
                                           (LOAD, 5, 0x1000, 0x401000, 0x200,
                                            0x300, align)), entry=entry))
    for n in (0, 1, 4, 16, 63, 64, 65, 100, 119, 120, 4095, 4096):
        check(good[:n])
    for i in range(64):
        for value in (0, 1, 2, 3, 7, 62, 64, 255):
            b = bytearray(good)
            b[i] = value
            check(bytes(b))
    # Every program-header field has targeted boundary and corruption cases.
    for field, fmt, vals in (
        (0, "<I", (0, 1, 2, 3, 4, 0xffffffff)),
        (4, "<I", (0, 1, 2, 3, 4, 5, 6, 7, 8, 0xffffffff)),
        (8, "<Q", (0, 1, 0xfff, 0x1000, 0x1001, 0x2000,
                    (1 << 63), (1 << 64) - 1)),
        (16, "<Q", (0, 4095, 4096, 0x401000, 0x401001, MAX_USER - 1,
                     MAX_USER, (1 << 64) - 1)),
        (32, "<Q", (0, 1, 0x100, 0x200, 0x201, 0x100000, (1 << 64) - 1)),
        (40, "<Q", (0, 1, 0x80, 0x100, 0x200, 0x201,
                     MAX_USER, (1 << 64) - 1)),
        (48, "<Q", (0, 1, 2, 3, 0x1000, 0x2000, 0x2001,
                     (1 << 63), (1 << 64) - 1)),
    ):
        for index in (0, 1):
            for val in vals:
                check(mutate_ph(good, index, field, fmt, val))
    for val in (0, 4095, 4096, 0x401000, 0x4010ff, 0x401100,
                MAX_USER - 1, MAX_USER):
        b = bytearray(good)
        struct.pack_into("<Q", b, 24, val)
        check(bytes(b))
    for phnum in (0, 1, 2, 3, 128, 129, 65535):
        b = bytearray(good)
        struct.pack_into("<H", b, 56, phnum)
        check(bytes(b))
    # Fuzz both headers and segment records, including truncation and
    # multi-field mutations, with deterministic independent reference.
    for _ in range(800):
        data = bytearray(good)
        for _ in range(rng.randrange(1, 5)):
            k = rng.randrange(5)
            if k == 0:
                data = data[:rng.randrange(len(data) + 1)]
                break
            if k == 1:
                idx = rng.randrange(64)
            else:
                idx = rng.randrange(64, 64 + 2 * PHDR)
            data[idx] = rng.randrange(256)
        check(bytes(data))
    if unsafe:
        assert mismatches >= 150, (mismatches, cases)
    else:
        assert mismatches == 0 and accepted >= 50, (accepted, cases)
    return {"schema": "heptakernel.hia-elf64-ptload.v1",
            "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
            "cases": cases, "accepted": accepted,
            "status_counts": status_counts,
            "independent_oracle_mismatches": mismatches,
            "native_hia": True, "elf_loader_implemented": False,
            "linux_full_acceptance": "HOLD"}


def text_hash(object_file: Path, library: Path) -> str:
    with tempfile.TemporaryDirectory() as temp:
        bodies = []
        for label, path in (("object", object_file), ("linked", library)):
            out = Path(temp) / label
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(path.resolve()), str(out)], check=True)
            body = out.read_bytes()
            assert body
            bodies.append(body)
        assert bodies[0] == bodies[1]
        return hashlib.sha256(bodies[0]).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--object", type=Path)
    ap.add_argument("--expect-unsafe", action="store_true")
    args = ap.parse_args()
    report = campaign(args.library, args.expect_unsafe)
    if args.object and not args.expect_unsafe:
        report["object_shared_text_sha256"] = text_hash(args.object, args.library)
    print(json.dumps(report, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/elf64-load-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
