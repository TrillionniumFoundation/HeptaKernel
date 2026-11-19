#!/usr/bin/env python3
"""Differential native HIA page-copy oracle and real read-only/guard-page test.

No host-side copying participates in the implementation being tested.
Non-overlap/ownership of the three capabilities remains the caller's duty.
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


def oracle(entry, *, source_len=PAGE, receipt_len=16, dest_len=PAGE, seed=1):
    rng = random.Random(seed)
    source = bytes(rng.randrange(256) for _ in range(source_len))
    destination = bytes(rng.randrange(256) for _ in range(dest_len))
    src = ctypes.create_string_buffer(b"\xa1" * CANARY + source + b"\xa1" * CANARY)
    rec = ctypes.create_string_buffer(b"\xb2" * (receipt_len + CANARY * 2))
    dst = ctypes.create_string_buffer(b"\xc3" * CANARY + destination + b"\xc3" * CANARY)
    src_before, rec_before, dst_before = bytes(src), bytes(rec), bytes(dst)
    status = entry(ctypes.addressof(src) + CANARY, source_len,
                   ctypes.addressof(rec) + CANARY, receipt_len,
                   ctypes.addressof(dst) + CANARY, dest_len)
    expected_status = (1 if source_len != PAGE else 2 if receipt_len != 16
                       else 3 if dest_len != PAGE else 0)
    if expected_status:
        expected_rec, expected_dst = rec_before, dst_before
    else:
        expected_rec = (b"\xb2" * CANARY + (0).to_bytes(8, "little")
                        + PAGE.to_bytes(8, "little") + b"\xb2" * CANARY + b"\x00")
        expected_dst = b"\xc3" * CANARY + source + b"\xc3" * CANARY + b"\x00"
    return (status == expected_status and bytes(src) == src_before
            and bytes(rec) == expected_rec and bytes(dst) == expected_dst)


def guarded_copy(entry):
    """Test actual CPU stores, with source PROT_READ and neighbors PROT_NONE."""
    if mmap.PAGESIZE != PAGE:
        return "SKIPPED_PAGE_SIZE_MISMATCH"
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    src_map = mmap.mmap(-1, 3 * PAGE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
    dst_map = mmap.mmap(-1, 3 * PAGE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
    src_buf = (ctypes.c_ubyte * (3 * PAGE)).from_buffer(src_map)
    dst_buf = (ctypes.c_ubyte * (3 * PAGE)).from_buffer(dst_map)
    src_base, dst_base = ctypes.addressof(src_buf), ctypes.addressof(dst_buf)
    original = bytes(range(256)) * 16
    ctypes.memmove(src_base + PAGE, original, PAGE)
    ctypes.memset(dst_base + PAGE, 0x5C, PAGE)
    for base in (src_base, dst_base):
        assert libc.mprotect(base, PAGE, 0) == 0
        assert libc.mprotect(base + 2 * PAGE, PAGE, 0) == 0
    assert libc.mprotect(src_base + PAGE, PAGE, mmap.PROT_READ) == 0
    try:
        receipt = ctypes.create_string_buffer(16)
        status = entry(src_base + PAGE, PAGE, ctypes.addressof(receipt), 16,
                       dst_base + PAGE, PAGE)
        assert status == 0
        assert receipt.raw == (0).to_bytes(8, "little") + PAGE.to_bytes(8, "little")
        assert ctypes.string_at(src_base + PAGE, PAGE) == original
        assert ctypes.string_at(dst_base + PAGE, PAGE) == original
        # Reject an overlong source without ever touching the inaccessible
        # region immediately after its valid 4 KiB capability.
        ctypes.memset(dst_base + PAGE, 0xB7, PAGE)
        status = entry(src_base + PAGE, PAGE + 1, ctypes.addressof(receipt), 16,
                       dst_base + PAGE, PAGE)
        assert status == 1 and ctypes.string_at(dst_base + PAGE, PAGE) == b"\xb7" * PAGE
    finally:
        assert libc.mprotect(src_base + PAGE, PAGE, mmap.PROT_READ | mmap.PROT_WRITE) == 0
        for base in (src_base, dst_base):
            assert libc.mprotect(base, PAGE, mmap.PROT_READ | mmap.PROT_WRITE) == 0
            assert libc.mprotect(base + 2 * PAGE, PAGE, mmap.PROT_READ | mmap.PROT_WRITE) == 0
        del src_buf, dst_buf
        src_map.close()
        dst_map.close()
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
    count, failures = 0, 0
    for seed in range(48):
        count += 1
        failures += not oracle(entry, seed=seed)
    for size in (0, 1, 4095, 4097, 8192):
        for seed in range(6):
            count += 1
            failures += not oracle(entry, source_len=size, seed=seed)
            count += 1
            failures += not oracle(entry, dest_len=size, seed=seed)
    for size in (0, 1, 8, 15, 17, 32):
        for seed in range(4):
            count += 1
            failures += not oracle(entry, receipt_len=size, seed=seed)
    if args.expect_unsafe:
        assert failures >= 48, (failures, count)
        print(json.dumps({"cases": count, "detected_mismatches": failures,
                          "dishonest_negative_control": "PASS"}, sort_keys=True))
    else:
        assert failures == 0, (failures, count)
        assert guarded_copy(entry) == "PASS"
        print(json.dumps({"cases": count, "oracle_mismatches": failures,
                          "readonly_source_and_guard_pages": "PASS",
                          "native_page_copy": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    main()
