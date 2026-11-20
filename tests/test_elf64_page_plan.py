#!/usr/bin/env python3
"""Independent ELF64 PT_LOAD -> page-fill plan oracle for real HIA native code.

This tests immutable image bytes and output authority. It is not an ELF loader,
an atomic publication transaction, a privileged page map, or full execve.
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

from test_elf64_load_segments import example, reference as full_layout_oracle

PHDR, PAGE, MAX_USER = 56, 4096, 1 << 47
LOAD, WRITE, EXEC = 1, 2, 1
MASK = (1 << 64) - 1


def oracle(image: bytes, selector: bytes, out_size: int = 40):
    if len(image) < 64:
        return 1, None
    if len(selector) != 16 or out_size != 40:
        return 2, None
    if (image[:4] != b"\x7fELF" or image[4:7] != b"\x02\x01\x01"
            or image[7] not in (0, 3) or image[8:16] != bytes(8)):
        return 3, None
    kind, machine, version = struct.unpack_from("<HHI", image, 16)
    if kind not in (2, 3) or machine != 62 or version != 1:
        return 3, None
    eh, ent, n = struct.unpack_from("<HHH", image, 52)
    phoff = struct.unpack_from("<Q", image, 32)[0]
    if (eh != 64 or ent != 56 or not 1 <= n <= 128
            or phoff < 64 or phoff > len(image) or phoff % 8
            or n * PHDR > len(image) - phoff):
        return 4, None
    phidx, pgidx = struct.unpack("<QQ", selector)
    if phidx >= n or pgidx > (1 << 20) - 1:
        return 5, None
    typ, flags, off, va, _phys, fs, ms, align = (
        struct.unpack_from("<IIQQQQQQ", image, phoff + phidx * PHDR))
    if typ != LOAD:
        return 5, None
    if flags & ~7 or flags & WRITE and flags & EXEC:
        return 6, None
    if (ms == 0 or fs > ms or ms > (1 << 32)
            or va < 4096 or va >= MAX_USER or ms > MAX_USER - va
            or off > len(image) or fs > len(image) - off
            or (off & 4095) != (va & 4095)
            or (align > 1 and ((align & (align - 1)) != 0
                              or (off & (align - 1)) != (va & (align - 1))))):
        return 6, None
    lead = va & 4095
    if pgidx * PAGE >= lead + ms:
        return 7, None
    return 0, struct.pack("<5Q", off, fs, ms, lead, pgidx)


def native(path: Path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    return f


def physical_page(image: bytes, plan: bytes) -> bytes:
    off, fs, _ms, lead, ix = struct.unpack("<5Q", plan)
    begin = ix * PAGE
    return bytes(image[off + x - lead] if lead <= x < lead + fs else 0
                 for x in range(begin, begin + PAGE))


def campaign(library: Path, fill_path: Path | None, unsafe: bool) -> dict:
    f = native(library)
    fill = native(fill_path) if fill_path else None
    rng = random.Random(202611202326)
    count = accepted = differences = integrated = 0
    errors: dict[int, int] = {}

    def check(image: bytes, selector: bytes, out_size: int = 40):
        nonlocal count, accepted, differences, integrated
        raw = ctypes.create_string_buffer(b"\xa5" * 32 + image + b"\xa5" * 32)
        sel = ctypes.create_string_buffer(b"\xb6" * 32 + selector + b"\xb6" * 32)
        plan = ctypes.create_string_buffer(b"\xc7" * 32 + b"\xe9" * out_size + b"\xc7" * 32)
        before = bytes(raw), bytes(sel), bytes(plan)
        result = f(ctypes.addressof(raw) + 32, len(image),
                   ctypes.addressof(sel) + 32, len(selector),
                   ctypes.addressof(plan) + 32, out_size)
        wanted, data = oracle(image, selector, out_size)
        actual_plan = bytes(plan)[32:32 + out_size]
        expected_plan = data if data is not None else b"\xe9" * out_size
        count += 1
        accepted += wanted == 0
        errors[wanted] = errors.get(wanted, 0) + 1
        mismatch = (result != wanted or actual_plan != expected_plan)
        differences += mismatch
        if not unsafe:
            assert not mismatch, (count, wanted, result,
                                  expected_plan.hex(), actual_plan.hex())
        assert bytes(raw) == before[0] and bytes(sel) == before[1], (
            "read-only image/selector changed", count)
        assert bytes(plan)[:32] == before[2][:32], "output left canary changed"
        assert bytes(plan)[32 + out_size:] == before[2][32 + out_size:], (
            "output right canary changed", count)
        if (fill and not unsafe and data is not None and
                full_layout_oracle(image) == 0):
            envelope = ctypes.create_string_buffer(data + image)
            receipt = ctypes.create_string_buffer(b"\xd4" * 16)
            page = ctypes.create_string_buffer(b"\xd3" * PAGE)
            fill_result = fill(ctypes.addressof(envelope), len(data) + len(image),
                               ctypes.addressof(receipt), 16,
                               ctypes.addressof(page), PAGE)
            assert fill_result == 0, ("HIA fill rejected verified plan", count)
            assert bytes(receipt)[:16] == b"\xa5" + bytes(15)
            assert bytes(page)[:PAGE] == physical_page(image, data), (
                "file-backed/BSS page bytes", count)
            assert bytes(envelope)[:len(data) + len(image)] == data + image
            integrated += 1

    base = example()
    for i in range(2):
        for page in (0, 1, 2, (1 << 20) - 1, 1 << 20, MASK):
            check(base, struct.pack("<QQ", i, page))
    for x in range(16):
        check(base, struct.pack("<QQ", 0, 0)[:x])
    for n in range(64):
        check(base[:n], struct.pack("<QQ", 0, 0))
    for size in (0, 1, 39, 40, 41):
        check(base, struct.pack("<QQ", 0, 0), size)
    for kind in (2, 3):
        for flag in (4, 5, 6):
            for fs, ms in ((0, 1), (1, 1), (80, 100), (180, 8192),
                           (4096, 12288), (5000, 12288)):
                for va, off, align in ((0x401000, 0x1000, 0x1000),
                                       (0x401080, 0x1080, 1)):
                    img = example(kind=kind, entries=(
                        (LOAD, 5, 0x1000, 0x401000, 128, 4096, 4096),
                        (LOAD, flag, off + 0x4000, va + 0x4000,
                         fs, ms, align)))
                    for page in (0, 1, 2, 3, 4):
                        check(img, struct.pack("<QQ", 1, page))
    for i in range(64):
        altered = bytearray(base)
        altered[i] = (altered[i] + 7) % 256
        check(bytes(altered), struct.pack("<QQ", 0, 0))
    for _ in range(700):
        altered = bytearray(base)
        if rng.random() < 0.6:
            off = 64 + rng.choice((0, 4, 8, 16, 32, 40, 48))
            fmt = "<I" if off in (64, 68) else "<Q"
            struct.pack_into(fmt, altered, off,
                             rng.getrandbits(32 if fmt == "<I" else 64))
        else:
            at = rng.randrange(min(128, len(altered)))
            altered[at] = rng.randrange(256)
        selector = struct.pack("<QQ", rng.choice((0, 1, 2, 127, MASK)),
                               rng.choice((0, 1, 2, MASK)))
        check(bytes(altered), selector)
    if unsafe:
        assert differences >= 150, (differences, count)
    else:
        assert differences == 0 and accepted >= 100 and integrated >= 10, (
            differences, accepted, integrated)
    return {"schema": "heptakernel.elf64-page-plan.v1",
            "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
            "cases": count, "accepted": accepted, "divergences": differences,
            "integrated_hia_page_fills": integrated,
            "status_counts": errors, "native_hia": True,
            "actual_elf_loader": False, "full_acceptance": "HOLD"}


def text_hash(obj: Path, library: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        hashes = []
        for index, src in enumerate((obj, library)):
            dest = Path(tmp) / str(index)
            subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                            str(src.resolve()), str(dest)], check=True)
            hashes.append(dest.read_bytes())
        assert hashes[0] and hashes[0] == hashes[1]
        return hashlib.sha256(hashes[0]).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--fill", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    result = campaign(args.library, args.fill, args.expect_unsafe)
    if args.object and not args.expect_unsafe:
        result["native_text_sha256"] = text_hash(args.object, args.library)
    print(json.dumps(result, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/elf64-page-plan-report.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
