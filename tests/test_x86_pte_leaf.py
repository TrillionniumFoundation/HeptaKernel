#!/usr/bin/env python3
"""Independent scalar oracle for HIA x86-64 4KiB PTE permission and CPU admission.

This is a policy/encoding unit, not a page-table walker, CR3 writer, or VM.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

PAGE = 4096
MAX_PHYSICAL = 1 << 52
MAX64 = (1 << 64) - 1
NX = 1 << 63
NXE = 1 << 8
PGE = 1 << 9
DEFAULT_CAPS = 52 | NXE | PGE


def oracle(raw: bytes, reply_size: int = 16):
    if reply_size < 16:
        return 1, None
    if len(raw) != 32:
        return 2, 0
    virtual, physical, flags, caps = struct.unpack("<4Q", raw)
    # CPUID 0x80000008 EAX[7:0] is MAXPHYADDR. Our explicit handoff also
    # binds CR4.PGE and EFER.NXE enablement, not merely CPUID support.
    width = caps & 0xff
    if caps & ~0x3ff or not 32 <= width <= 52:
        return 6, 0
    upper = virtual >> 48
    sign = bool(virtual & (1 << 47))
    canonical = (upper == 0) if not sign else (upper == 0xffff)
    if (virtual % PAGE or physical % PAGE or physical >= (1 << width)
            or not canonical or flags > 31 or not flags & 1):
        return 6, 0
    writable = bool(flags & 2)
    executable = bool(flags & 4)
    user = bool(flags & 8)
    global_page = bool(flags & 16)
    if ((writable and executable) or (user and global_page)
            or (user and sign)):
        return 7, 0
    if (not executable and not (caps & NXE)) or (global_page and not (caps & PGE)):
        return 8, 0
    # Independent integer bit assembly, deliberately not using HIA CFG.
    result = physical | 1
    if writable:
        result |= 1 << 1
    if user:
        result |= 1 << 2
    if global_page:
        result |= 1 << 8
    if not executable:
        result |= NX
    return 0, result


def pack(virtual: int, physical: int, flags: int, caps: int = DEFAULT_CAPS) -> bytes:
    return struct.pack("<4Q", virtual, physical, flags, caps)


def campaign(library: Path) -> dict:
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    count = 0

    def check(raw: bytes, reply_size: int = 16):
        nonlocal count
        request = ctypes.create_string_buffer(b"\xa5" * 32 + raw + b"\xa5" * 32)
        reply = ctypes.create_string_buffer(b"\xb6" * (reply_size + 64))
        unused = ctypes.create_string_buffer(b"\xc7" * 64)
        before_req = bytes(request)
        before_unused = bytes(unused)
        rv = native(ctypes.addressof(request) + 32, len(raw),
                    ctypes.addressof(reply) + 32, reply_size,
                    ctypes.addressof(unused), 64)
        assert bytes(request) == before_req, "modified immutable PTE request"
        assert bytes(unused) == before_unused, "modified unused capability"
        response = bytes(reply)
        assert response[:32] == b"\xb6" * 32
        assert response[32 + reply_size: 32 + reply_size + 32] == b"\xb6" * 32
        if reply_size < 16:
            assert response == b"\xb6" * (reply_size + 64) + b"\0"
            got = rv, None
        else:
            returned, value = struct.unpack_from("<2Q", response, 32)
            assert response[48:32 + reply_size] == b"\xb6" * (reply_size - 16)
            assert rv == returned
            got = returned, value
        expected = oracle(raw, reply_size)
        assert got == expected, {"expected": expected, "actual": got, "raw": raw.hex()}
        count += 1

    low_max = (1 << 47) - PAGE
    high_min = MAX64 - (1 << 47) + 1
    for va in (0, PAGE, 0x400000, low_max, high_min, MAX64 - PAGE + 1):
        for pa in (0, PAGE, 0x400000, MAX_PHYSICAL - PAGE, MAX_PHYSICAL):
            for flags in range(0, 36):
                check(pack(va, pa, flags))
    for va in (low_max + PAGE, 1 << 47, high_min - PAGE, MAX64, 0x8000000000001000):
        for flags in (1, 3, 5, 9, 17, 31):
            check(pack(va, PAGE, flags))
    # CPU width and control-register admission must be checked before a
    # dynamic HIA shift: a width >= 64 must refuse, never trap.
    for caps in (0, 1, 31, 32, 36, 52, 53, 63, 64, 255, 256,
                 32 | NXE, 36 | NXE, 52 | NXE, 52 | PGE,
                 DEFAULT_CAPS, DEFAULT_CAPS | (1 << 10), MAX64):
        for va in (0, 0x400000, high_min):
            for pa in (0, (1 << 32) - PAGE, 1 << 32,
                       (1 << 36) - PAGE, 1 << 36,
                       MAX_PHYSICAL - PAGE, MAX_PHYSICAL):
                for flags in (1, 3, 5, 9, 17, 19, 31):
                    check(pack(va, pa, flags, caps))
    for raw in (b"", b"\0" * 23, b"\0" * 24, b"\0" * 31, b"\0" * 33,
                pack(0x400000, PAGE, 1) + b"\0"):
        check(raw)
    for reply_size in (0, 1, 8, 15, 16, 17, 32):
        check(pack(0x400000, PAGE, 3), reply_size)
    rng = random.Random(0x58C01)
    vas = [0, 0x1000, low_max, high_min, MAX64 - PAGE + 1, 1 << 47,
           high_min - PAGE]
    for _ in range(1800):
        va = rng.choice(vas) if rng.randrange(4) else rng.getrandbits(64)
        pa = rng.choice([rng.randrange(MAX_PHYSICAL // PAGE) * PAGE,
                         MAX_PHYSICAL - PAGE, MAX_PHYSICAL, MAX64,
                         rng.getrandbits(64)])
        flags = rng.randrange(0, 64)
        caps = rng.choice([DEFAULT_CAPS, 32 | NXE, 36 | NXE | PGE,
                           52 | NXE, 52 | PGE, 32, 52, 63, 64,
                           DEFAULT_CAPS | (1 << 12)])
        check(pack(va, pa, flags, caps))
    return {"status": "PASS", "cases": count}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as e:
            print("dishonest native HIA PTE policy rejected:", str(e)[:400])
            return
        raise SystemExit("dishonest PTE policy unexpectedly passed independent oracle")
    result = campaign(args.library)
    Path("build/x86-pte-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print("native HIA x86-64 PTE policy:", result["cases"], "independent cases PASS")


if __name__ == "__main__":
    main()
