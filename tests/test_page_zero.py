#!/usr/bin/env python3
"""Independent byte-level oracle for native HIA page zeroing.

The native entry must zero exactly one owned 4KiB mutable capability, without
touching adjacent sentinels or any caller buffers on malformed capability
shapes. This is not physical frame ownership or concurrent safety evidence.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import mmap
import random
from pathlib import Path

PAGE = 4096
CANARY = 32


def call(entry, *, request=b"", reply_len=16, page_len=PAGE, seed=1):
    rng = random.Random(seed)
    original = bytes(rng.randrange(1, 256) for _ in range(page_len))
    req = ctypes.create_string_buffer(b"\xa7" * CANARY + request + b"\xa7" * CANARY)
    rep = ctypes.create_string_buffer(b"\xb8" * (reply_len + 2 * CANARY))
    mem = ctypes.create_string_buffer(b"\xc9" * CANARY + original + b"\xc9" * CANARY)
    request_before = bytes(req)
    before_reply = bytes(rep)
    result = entry(ctypes.addressof(req) + CANARY, len(request),
                   ctypes.addressof(rep) + CANARY, reply_len,
                   ctypes.addressof(mem) + CANARY, page_len)
    assert bytes(req) == request_before, "native modified read-only request"
    actual_reply, actual_page = bytes(rep), bytes(mem)
    assert actual_reply[:CANARY] == b"\xb8" * CANARY
    assert actual_reply[CANARY + reply_len:CANARY + reply_len + CANARY] == b"\xb8" * CANARY
    assert actual_page[:CANARY] == b"\xc9" * CANARY
    assert actual_page[CANARY + page_len:CANARY + page_len + CANARY] == b"\xc9" * CANARY
    expected_status = (1 if request else 2 if reply_len != 16
                       else 3 if page_len != PAGE else 0)
    if expected_status:
        expected_reply, expected_page = before_reply, b"\xc9" * CANARY + original + b"\xc9" * CANARY + b"\x00"
    else:
        expected_reply = (b"\xb8" * CANARY + (0).to_bytes(8, "little")
                          + PAGE.to_bytes(8, "little") + b"\xb8" * CANARY + b"\x00")
        expected_page = b"\xc9" * CANARY + bytes(PAGE) + b"\xc9" * CANARY + b"\x00"
    return (result == expected_status and actual_reply == expected_reply
            and actual_page == expected_page), expected_status, result


def guarded_page(entry):
    """Keep both neighbors PROT_NONE during actual native stores."""
    if PAGE != mmap.PAGESIZE:
        return "SKIPPED_PAGE_SIZE_MISMATCH"
    mapping = mmap.mmap(-1, 3 * PAGE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
    marker = (ctypes.c_ubyte * (3 * PAGE)).from_buffer(mapping)
    base = ctypes.addressof(marker)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    assert libc.mprotect(base, PAGE, 0) == 0
    assert libc.mprotect(base + 2 * PAGE, PAGE, 0) == 0
    try:
        ctypes.memset(base + PAGE, 0xD5, PAGE)
        req = ctypes.create_string_buffer(1)
        rep = ctypes.create_string_buffer(16)
        status = entry(ctypes.addressof(req), 0, ctypes.addressof(rep), 16,
                       base + PAGE, PAGE)
        assert status == 0 and bytes(rep.raw) == (0).to_bytes(8, "little") + PAGE.to_bytes(8, "little")
        assert ctypes.string_at(base + PAGE, PAGE) == bytes(PAGE)
        # Length rejection must occur before any store even if supplied
        # size runs over the adjacent OS-inaccessible page.
        ctypes.memset(base + PAGE, 0xC3, PAGE)
        before = bytes(rep.raw)
        status = entry(ctypes.addressof(req), 0, ctypes.addressof(rep), 16,
                       base + PAGE, PAGE + 1)
        assert status == 3 and bytes(rep.raw) == before
        assert ctypes.string_at(base + PAGE, PAGE) == b"\xc3" * PAGE
    finally:
        assert libc.mprotect(base, PAGE, mmap.PROT_READ | mmap.PROT_WRITE) == 0
        assert libc.mprotect(base + 2 * PAGE, PAGE, mmap.PROT_READ | mmap.PROT_WRITE) == 0
        del marker
        mapping.close()
    return "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    dll = ctypes.CDLL(str(args.library.resolve()))
    entry = dll.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint32
    failures, count = 0, 0
    for seed in range(32):
        good, _, _ = call(entry, seed=seed)
        count += 1
        failures += not good
    for request in (b"\x00", b"\x01" * 8, b"\xff" * 32):
        for size in (0, 16, 4095, 4096, 4097):
            good, _, _ = call(entry, request=request, page_len=size, seed=17)
            count += 1
            failures += not good
    for reply_len in (0, 1, 8, 15, 17, 64):
        for size in (0, 1, 4095, 4096, 4097):
            good, _, _ = call(entry, reply_len=reply_len, page_len=size, seed=23)
            count += 1
            failures += not good
    for size in (0, 1, 4095, 4097, 8192):
        good, _, _ = call(entry, page_len=size, seed=99)
        count += 1
        failures += not good
    if args.expect_unsafe:
        assert failures > 32, ("dishonest HIA implementation escaped detection", failures)
        print(json.dumps({"cases": count, "dishonest_mismatches": failures,
                          "negative_control": "PASS"}))
    else:
        assert not failures, ("native HIA vs independent zero-page byte oracle", failures, count)
        hardware_guard = guarded_page(entry)
        assert hardware_guard == "PASS", hardware_guard
        print(json.dumps({"cases": count, "oracle_mismatches": failures,
                          "guard_pages": hardware_guard,
                          "native_zero": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    main()
