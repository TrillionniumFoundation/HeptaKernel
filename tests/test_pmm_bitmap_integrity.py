#!/usr/bin/env python3
"""Independent byte-level PMM free-count oracle, native ABI and dishonest control.

A successful read-only check does not authenticate its pointer, lock a PMM,
or establish a kernel transaction. Every buffer and canary is checked.
"""
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

MAGIC = 0x314D4D504B484941
PAGE = 4096
LIMIT = 1 << 52

def oracle(req, state):
    if len(req) != 24 or len(state) < 64:
        return 1
    base, pages, prefix = struct.unpack("<3Q", req)
    magic, count, start, reserve, free = struct.unpack_from("<5Q", state)
    if (magic, count, start, reserve) != (MAGIC, pages, base, prefix):
        return 2
    if not (0 < pages <= 65536 and prefix <= pages
            and base % PAGE == 0 and base < LIMIT
            and pages * PAGE <= LIMIT - base
            and free <= pages - prefix
            and len(state) >= 64 + (pages + 7) // 8):
        return 3
    if any(state[40:64]):
        return 4
    missing = 0
    for index in range(((pages + 7) // 8) * 8):
        bit = bool(state[64 + index // 8] & (1 << (index % 8)))
        if index < prefix and not bit:
            return 4
        if index >= pages and bit:
            return 4
        if prefix <= index < pages and not bit:
            missing += 1
    return 0 if missing == free else 5

def valid(rng, pages, prefix, extra=0):
    base = 0x600000
    bitmap = bytearray((pages + 7) // 8)
    for i in range(pages):
        if i < prefix or rng.randrange(2):
            bitmap[i // 8] |= 1 << (i % 8)
    free = sum(not (bitmap[i // 8] & (1 << (i % 8))) for i in range(prefix, pages))
    return (struct.pack("<3Q", base, pages, prefix),
            struct.pack("<5Q", MAGIC, pages, base, prefix, free) +
            bytes(24) + bytes(bitmap) + bytes(extra))

def native(lib):
    f = ctypes.CDLL(str(Path(lib).resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    return f

def invoke(f, request, state):
    buffers = []
    for data, sentinel in ((request, 0xC3), (state, 0xA5), (b"\x00", 0xB7)):
        pad = 32
        mem = (ctypes.c_ubyte * (len(data) + 2 * pad))()
        ctypes.memset(ctypes.addressof(mem), sentinel, len(mem))
        ctypes.memmove(ctypes.addressof(mem) + pad, data, len(data))
        buffers.append((mem, bytes(mem), len(data)))
    params = []
    for mem, _, length in buffers:
        params.extend((ctypes.addressof(mem) + 32, length))
    got = f(*params)
    for mem, before, length in buffers:
        assert bytes(mem) == before, ("write to read-only PMM or canary", length, got)
    return got

def run():
    p = argparse.ArgumentParser()
    p.add_argument("library")
    p.add_argument("--expect-unsafe", action="store_true")
    args = p.parse_args()
    rng = random.Random(0xB17A5EED)
    cases = []
    for count in (1, 2, 7, 8, 9, 17, 31, 64, 65, 255, 256, 1024):
        for reserved in sorted({0, 1, count // 2, count}):
            if reserved > count:
                continue
            for _ in range(4):
                cases.append(valid(rng, count, reserved, rng.randrange(3)))
    for _ in range(180):
        count = rng.randint(1, 2048)
        cases.append(valid(rng, count, rng.randint(0, count)))
    request, state = valid(rng, 17, 2)
    cases.append((request, state))
    for length in (0, 1, 7, 8, 23, 25):
        cases.append((request[:length], state))
    for length in (0, 1, 39, 63, 64, 65, 66):
        cases.append((request, state[:length]))
    for offset in range(64):
        corrupted = bytearray(state)
        corrupted[offset] ^= 1 << (offset % 8)
        cases.append((request, bytes(corrupted)))
    for offset in range(24):
        corrupted = bytearray(request)
        corrupted[offset] ^= 1 << (offset % 8)
        cases.append((bytes(corrupted), state))
    # All three kinds of integrity failures must be visible independently.
    corrupt = bytearray(state)
    corrupt[64] &= ~1
    cases.append((request, bytes(corrupt)))
    corrupt = bytearray(state)
    struct.pack_into("<Q", corrupt, 32, 16)
    cases.append((request, bytes(corrupt)))
    corrupt = bytearray(state)
    corrupt[66] |= 1 << 7
    cases.append((request, bytes(corrupt)))
    for _ in range(520):
        count = rng.choice((9, 17, 65, 255, 256, 1024))
        req, state = valid(rng, count, rng.randrange(count + 1))
        w, st = bytearray(req), bytearray(state)
        choice = rng.randrange(5)
        if choice == 0:
            st[64 + rng.randrange((count + 7) // 8)] ^= 1 << rng.randrange(8)
        elif choice == 1:
            struct.pack_into("<Q", st, 32, rng.randrange(count + 2))
        elif choice == 2:
            st[40 + rng.randrange(24)] = rng.randrange(1, 256)
        elif choice == 3:
            w[rng.randrange(24)] ^= 1 << rng.randrange(8)
        else:
            st[8 + rng.randrange(32)] ^= 1 << rng.randrange(8)
        cases.append((bytes(w), bytes(st)))
    f = native(args.library)
    missed = 0
    positive = 0
    for i, (req, state) in enumerate(cases):
        expected, got = oracle(req, state), invoke(f, req, state)
        if args.expect_unsafe:
            missed += int(got != expected)
        else:
            assert got == expected, (i, got, expected, len(req), len(state))
            positive += int(got == 0)
    if args.expect_unsafe:
        assert missed >= 100, missed
    else:
        assert positive >= 100, positive
    print(json.dumps({"schema": "heptakernel.pmm-bitmap-integrity.v1",
                      "cases": len(cases), "positive": positive,
                      "dishonest_detections": missed,
                      "status": "DISHONEST_DETECTED" if args.expect_unsafe else "PASS"}, sort_keys=True))

if __name__ == "__main__":
    run()
