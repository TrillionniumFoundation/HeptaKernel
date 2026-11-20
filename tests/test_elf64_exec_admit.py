#!/usr/bin/env python3
"""Independent adversarial ELF64 header admission oracle for real HIA native code.

This is neither an ELF program-header parser nor an executable loader. It
does not prove PT_LOAD permissions, file-to-memory copies, relocation, ABI
layout, user stack setup, or Linux execve behavior.
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

HDR = 64
PHDR = 56
MAX_USER = 1 << 47


def reference(data: bytes) -> int:
    if len(data) < HDR:
        return 1
    if data[:4] != b"\x7fELF":
        return 2
    if (data[4:7] != b"\x02\x01\x01"
            or data[7] not in (0, 3)
            or any(data[8:16])):
        return 3
    etype, machine, version = struct.unpack_from("<HHI", data, 16)
    if etype not in (2, 3) or machine != 62 or version != 1:
        return 4
    ehsize, phentsize, phnum = struct.unpack_from("<HHH", data, 52)
    if ehsize != HDR or phentsize != PHDR or not 1 <= phnum <= 65534:
        return 5
    entry = struct.unpack_from("<Q", data, 24)[0]
    if not 4096 <= entry < MAX_USER:
        return 7
    phoff = struct.unpack_from("<Q", data, 32)[0]
    if phoff < HDR or phoff > len(data) or phoff % 8:
        return 6
    if phnum * PHDR > len(data) - phoff:
        return 6
    return 0


def example(*, kind: int = 2, n: int = 1, phoff: int = 64,
            entry: int = 0x401000, osabi: int = 0) -> bytes:
    end = max(HDR, phoff + PHDR * n) if phoff <= 32768 and n <= 64 else 256
    data = bytearray(end)
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes((osabi,)) + bytes(8)
    struct.pack_into("<HHI", data, 16, kind, 62, 1)
    struct.pack_into("<Q", data, 24, entry)
    struct.pack_into("<Q", data, 32, phoff)
    struct.pack_into("<HHH", data, 52, HDR, PHDR, n)
    return bytes(data)


def native_function(path: Path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    return f


def campaign(path: Path, unsafe: bool = False) -> dict:
    f = native_function(path)
    rng = random.Random(202611201327)
    cases = accepted = mismatches = 0

    def check(data: bytes):
        nonlocal cases, accepted, mismatches
        request = ctypes.create_string_buffer(b"\xa7" * 32 + data + b"\xa7" * 32)
        output = ctypes.create_string_buffer(b"\xb8" * 128)
        scratch = ctypes.create_string_buffer(b"\xc9" * 128)
        before = (bytes(request), bytes(output), bytes(scratch))
        actual = f(ctypes.addressof(request) + 32, len(data),
                   ctypes.addressof(output) + 32, 64,
                   ctypes.addressof(scratch) + 32, 64)
        expected = reference(data)
        cases += 1
        accepted += expected == 0
        mismatches += actual != expected
        if not unsafe:
            assert actual == expected, (cases, expected, actual, data[:64].hex())
        assert (bytes(request), bytes(output), bytes(scratch)) == before, (
            "input/canary/unused mutable buffer corrupted", cases)

    for kind in (2, 3):
        for abi in (0, 3):
            for n in (1, 2, 3, 16, 32):
                for phoff in (64, 72, 128, 4096):
                    check(example(kind=kind, n=n, phoff=phoff, osabi=abi))
    seed = example()
    for length in (0, 1, 4, 7, 16, 31, 56, 63, 64, 65, 119, 120):
        check(seed[:length])
    for i in range(64):
        for val in (0, 1, 2, 3, 15, 62, 64, 127, 255):
            changed = bytearray(seed)
            changed[i] = val
            check(bytes(changed))
    # Exact header manipulations distinguish section headers from program
    # headers and exercise 64-bit offsets and 16-bit counts.
    for off in (0, 1, 63, 64, 65, 71, 72, 120, 121, 127,
                (1 << 63), (1 << 64) - 64):
        changed = bytearray(seed)
        struct.pack_into("<Q", changed, 32, off)
        check(bytes(changed))
    for num in (0, 1, 2, 3, 65534, 65535):
        changed = bytearray(seed)
        struct.pack_into("<H", changed, 56, num)
        check(bytes(changed))
    for entry in (0, 1, 4095, 4096, MAX_USER - 1, MAX_USER,
                  (1 << 48), (1 << 63), (1 << 64) - 1):
        changed = bytearray(seed)
        struct.pack_into("<Q", changed, 24, entry)
        check(bytes(changed))
    for _ in range(900):
        data = bytearray(example(kind=rng.choice((2, 3)),
                                 phoff=rng.choice((64, 72, 128, 4096))))
        for _ in range(rng.randrange(1, 5)):
            if rng.randrange(7) == 0:
                data = data[:rng.randrange(0, len(data) + 1)]
                break
            index = rng.randrange(min(len(data), 64))
            data[index] = rng.randrange(256)
        check(bytes(data))
    if unsafe:
        assert mismatches > 200, (mismatches, cases)
    else:
        assert mismatches == 0 and accepted >= 160, (accepted, cases)
    return {
        "schema": "heptakernel.hia-elf64-exec-admit.v1",
        "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
        "cases": cases, "accepted": accepted,
        "independent_oracle_mismatches": mismatches,
        "native_hia": True, "elf_loading_implemented": False,
        "linux_full_acceptance": "HOLD",
    }


def text_hash(obj: Path, lib: Path) -> str:
    with tempfile.TemporaryDirectory() as d:
        bodies = []
        for name, path in (("obj", obj), ("lib", lib)):
            dest = Path(d) / name
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(path.resolve()), str(dest)], check=True)
            body = dest.read_bytes()
            assert body
            bodies.append(body)
        assert bodies[0] == bodies[1]
        return hashlib.sha256(bodies[0]).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    a = parser.parse_args()
    report = campaign(a.library, a.expect_unsafe)
    if a.object and not a.expect_unsafe:
        report["object_shared_text_sha256"] = text_hash(a.object, a.library)
    print(json.dumps(report, sort_keys=True))
    if not a.expect_unsafe:
        Path("build/elf64-exec-admit-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
