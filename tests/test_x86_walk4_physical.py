#!/usr/bin/env python3
"""Independent oracle for HIA CR3-rooted traversal in a copied physical window.

The four physical pages are deliberately permuted in the 16KiB backing
window. No caller-selected L3/L2/L1 physical identities are supplied.
The backing itself is untrusted caller data, not authenticated RAM.
"""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import random
import struct

from test_x86_walk4_entries import independent_oracle as oracle_4k, compare_text
from test_x86_walk4_huge import independent_oracle as oracle_huge

PAGE = 4096
TOTAL = 4 * PAGE
MASK64 = (1 << 64) - 1
ADDRESS = ((1 << 52) - 1) & ~(PAGE - 1)
HIGH_RESERVED = ((1 << 63) - 1) & ~((1 << 52) - 1)
PARENT_BAD = 0x180


def oracle(request: bytes, pages: bytes, reply_size: int):
    if reply_size < 16:
        return 1, None
    if len(request) != 32:
        return 2, 0
    if len(pages) != TOTAL:
        return 3, 0
    va, bits, cr3, base = struct.unpack("<4Q", request)
    if not 32 <= bits <= 52:
        return 4, 0
    limit = 1 << bits
    root = cr3 & ADDRESS
    if ((cr3 & 4095) & ~24 or cr3 >= limit or root == 0 or
            base == 0 or base & 4095 or base >= limit or
            base + TOTAL > limit):
        return 4, 0

    def included(addr):
        return base <= addr < base + TOTAL and (addr & 4095) == 0

    def parent_ok(entry):
        return bool((entry & 1) and not (entry & PARENT_BAD) and
                    not (entry & HIGH_RESERVED) and (entry & ADDRESS))

    def read(page, level):
        index = (va >> (39 - 9 * level)) & 511
        return struct.unpack_from("<Q", pages, page - base + index * 8)[0]

    if not included(root):
        return 5, 0
    e4 = read(root, 0)
    if not parent_ok(e4):
        return 6, 0
    next_page = e4 & ADDRESS
    if not included(next_page):
        return 5, 0
    e3 = read(next_page, 1)
    if e3 & 128:
        translated = oracle_huge(va, e4, e3, 0, bits, 30)
        return (0, translated) if translated else (6, 0)
    if not parent_ok(e3):
        return 6, 0
    next_page = e3 & ADDRESS
    if not included(next_page):
        return 5, 0
    e2 = read(next_page, 2)
    if e2 & 128:
        translated = oracle_huge(va, e4, e3, e2, bits, 21)
        return (0, translated) if translated else (6, 0)
    if not parent_ok(e2):
        return 6, 0
    next_page = e2 & ADDRESS
    if not included(next_page):
        return 5, 0
    e1 = read(next_page, 3)
    translated = oracle_4k(va, e4, e3, e2, e1, bits)
    return (0, translated) if translated else (6, 0)


def fixture(rng, va, *, mode=12, bits=52, base=0x100000, order=None,
            cr3_flags=0, mutate=None):
    # Page order is explicitly independent of level order.
    order = list(range(4)) if order is None else list(order)
    positions = [base + i * PAGE for i in order]
    request = struct.pack("<4Q", va, bits, positions[0] | cr3_flags, base)
    pages = bytearray(rng.randbytes(TOTAL))
    leaf = {12: 0x8000000000006007, 21: 0x200087, 30: 0x40000087}[mode]
    entries = [positions[1] | 7, positions[2] | 7, positions[3] | 7, leaf]
    if mode == 21:
        entries[2] = leaf
    if mode == 30:
        entries[1] = leaf
    if mutate is not None:
        level, xor_value = mutate
        entries[level] ^= xor_value
    for level, page in enumerate(positions):
        idx = (va >> (39 - 9 * level)) & 511
        struct.pack_into("<Q", pages, page - base + idx * 8, entries[level])
    return request, bytes(pages)


def campaign(library: Path, object_file=None):
    fn = ctypes.CDLL(str(library.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    rng = random.Random(0xC33A97)
    counts = dict(cases=0, accepted=0, refused=0,
                  admitted_4k=0, admitted_2m=0, admitted_1g=0,
                  link_refusals=0)

    def check(req, pages, reply_size=16, mode=None):
        status, value = oracle(req, pages, reply_size)
        input_guard = b"\xa9" * 32
        memory_guard = b"\xc3" * 32
        reply_guard = b"\xe7" * 32
        inp = input_guard + req + input_guard
        mem = memory_guard + pages + memory_guard
        rep = reply_guard + b"\xb6" * reply_size + reply_guard
        in_array = (ctypes.c_ubyte * len(inp)).from_buffer_copy(inp)
        mem_array = (ctypes.c_ubyte * len(mem)).from_buffer_copy(mem)
        rep_array = (ctypes.c_ubyte * len(rep)).from_buffer_copy(rep)
        actual_status = fn(ctypes.addressof(in_array) + 32, len(req),
                           ctypes.addressof(rep_array) + 32, reply_size,
                           ctypes.addressof(mem_array) + 32, len(pages))
        assert actual_status == status, (actual_status, status, req.hex())
        assert bytes(in_array) == inp, "request corrupted"
        assert bytes(mem_array) == mem, "physical snapshot corrupted"
        actual_reply = bytes(rep_array)
        assert actual_reply[:32] == reply_guard
        assert actual_reply[-32:] == reply_guard
        if reply_size < 16:
            assert actual_reply == rep, "short response overwritten"
        else:
            assert struct.unpack_from("<2Q", actual_reply, 32) == (status, value)
            assert actual_reply[48:-32] == b"\xb6" * (reply_size - 16)
        counts["cases"] += 1
        counts["accepted" if status == 0 else "refused"] += 1
        if status == 5:
            counts["link_refusals"] += 1
        if status == 0 and mode is not None:
            counts[{12: "admitted_4k", 21: "admitted_2m",
                    30: "admitted_1g"}[mode]] += 1

    vas = [0, 0x123, 0xfff, 0x1000, 0x7fffffffffff,
           0xffff800000000000, 0xffffffffffffffff,
           0x0000800000000000, 0xffff7fffffffffff]
    for mode in (12, 21, 30):
        for i in range(250):
            va = rng.choice(vas + [rng.getrandbits(64)])
            bits = rng.choice([32, 36, 48, 52])
            order = rng.sample(range(4), 4)
            req, pages = fixture(rng, va, mode=mode, bits=bits,
                                 order=order, cr3_flags=rng.choice([0, 8, 16, 24]))
            check(req, pages, mode=mode)
            # Force a wrong physical link, an unsupported parent leaf, or
            # a violated permission in exactly one traversed entry.
            level = rng.randrange({12: 4, 21: 3, 30: 2}[mode])
            bit = rng.choice([0, 1, 2, 7, 8, 12, 13, 52, 60, 63])
            check(*fixture(rng, va, mode=mode, bits=bits, order=order,
                           mutate=(level, 1 << bit)), mode=mode)

    for va in vas:
        for mode in (12, 21, 30):
            req, pages = fixture(rng, va, mode=mode, order=[2, 0, 3, 1])
            check(req, pages, mode=mode)
            for bad_root in (0, 1, 0x1001, (1 << 52), MASK64, 0x100000, 0x106000):
                fields = list(struct.unpack("<4Q", req))
                fields[2] = bad_root
                check(struct.pack("<4Q", *fields), pages)
            for bad_base in (0, 1, 0xfff, (1 << 52), MASK64):
                fields = list(struct.unpack("<4Q", req))
                fields[3] = bad_base
                check(struct.pack("<4Q", *fields), pages)
            for bad_bits in (0, 31, 53, 64, MASK64):
                fields = list(struct.unpack("<4Q", req))
                fields[1] = bad_bits
                check(struct.pack("<4Q", *fields), pages)
            for size in (0, 1, PAGE, TOTAL - 1, TOTAL + 1):
                altered = pages[:size] if size <= TOTAL else pages + b"\0"
                check(req, altered)
            for size in (0, 1, 8, 15, 16, 17, 32):
                check(req, pages, size)
            for bad in (b"", b"\0" * 16, req[:-1], req + b"\0"):
                check(bad, pages)

    for i in range(800):
        mode = rng.choice((12, 21, 30))
        va = rng.choice(vas + [rng.getrandbits(64)])
        order = rng.sample(range(4), 4)
        req, pages = fixture(rng, va, mode=mode, order=order,
                             bits=rng.choice((32, 36, 48, 52)))
        if rng.randrange(2):
            fields = list(struct.unpack("<4Q", req))
            fields[rng.randrange(4)] ^= 1 << rng.randrange(64)
            req = struct.pack("<4Q", *fields)
        else:
            altered = bytearray(pages)
            level = rng.randrange(4)
            off = (order[level] * PAGE) + (((va >> (39 - 9 * level)) & 511) * 8)
            old = struct.unpack_from("<Q", altered, off)[0]
            struct.pack_into("<Q", altered, off, old ^ (1 << rng.randrange(64)))
            pages = bytes(altered)
        check(req, pages, mode=mode)

    assert counts["accepted"] > 200 and counts["refused"] > 500, counts
    assert counts["link_refusals"] > 30, counts
    assert all(counts[k] >= 80 for k in ("admitted_4k", "admitted_2m",
                                         "admitted_1g")), counts
    report = dict(schema="heptakernel.hia-cr3-rooted-physical-window.v1",
                  status="PASS", **counts, native_hia=True,
                  fixed_physical_window_bytes=TOTAL,
                  caller_supplied_snapshot=True, authenticated_physical_ram=False,
                  hardware_cr3_read=False, smp_safe=False,
                  linux_full_acceptance="HOLD")
    if object_file:
        report["object_shared_text_sha256"] = compare_text(object_file, library)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        fn = ctypes.CDLL(str(args.library.resolve())).f0
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        fn.restype = ctypes.c_uint32
        inp = ctypes.create_string_buffer(1)
        rep = ctypes.create_string_buffer(16)
        pages = ctypes.create_string_buffer(TOTAL)
        actual = fn(inp, 0, rep, 16, pages, TOTAL)
        assert oracle(b"", bytes(TOTAL), 16)[0] == 2
        assert actual == 0, "native HIA always-accept control is no longer dishonest"
        print("Dishonest HIA CR3-rooted physical walker: REJECTED")
        return
    report = campaign(args.library, args.object)
    Path("build/x86-walk4-physical-report.json").write_text(
        json.dumps(report, indent=2) + "\n")
    print("Native HIA CR3-rooted snapshot walker:",
          json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
