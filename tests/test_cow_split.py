#!/usr/bin/env python3
"""Independent byte-level COW detach+copy oracle for native HIA Core v8.

The caller owns three non-overlapping capabilities under exclusive quiescence.
This is NOT an atomic refcount, an authenticated PMM handle, a page fault,
or an SMP-safe Linux COW implementation.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import mmap
import random
from pathlib import Path

PAGE = 4096
HEADER = 16
SLOTS = PAGE - HEADER
PAD = 32


def reference(source: bytes, destination: bytes, state: bytes) -> tuple[int, bytes, bytes]:
    if len(source) != PAGE:
        return 1, destination, state
    if len(destination) != PAGE:
        return 2, destination, state
    if len(state) != PAGE:
        return 3, destination, state
    if any(state[6:HEADER]):
        return 4, destination, state
    src = int.from_bytes(state[0:2], "little")
    dst = int.from_bytes(state[2:4], "little")
    if src >= SLOTS or dst >= SLOTS or src == dst:
        return 5, destination, state
    expected, expected_dst = state[4], state[5]
    if state[HEADER + src] != expected or state[HEADER + dst] != expected_dst:
        return 6, destination, state
    if expected < 2 or expected_dst != 0:
        return 7, destination, state
    next_state = bytearray(state)
    next_state[HEADER + src] = expected - 1
    next_state[HEADER + dst] = 1
    return 0, source, bytes(next_state)


def invoke(entry, source: bytes, destination: bytes, state: bytes) -> bool:
    a = ctypes.create_string_buffer(b"\xa5" * PAD + source + b"\xa5" * PAD)
    b = ctypes.create_string_buffer(b"\xb6" * PAD + destination + b"\xb6" * PAD)
    c = ctypes.create_string_buffer(b"\xc7" * PAD + state + b"\xc7" * PAD)
    original_a, original_b, original_c = bytes(a), bytes(b), bytes(c)
    result = entry(ctypes.addressof(a) + PAD, len(source),
                   ctypes.addressof(b) + PAD, len(destination),
                   ctypes.addressof(c) + PAD, len(state))
    status, wanted_dst, wanted_state = reference(source, destination, state)
    expected_b = bytearray(original_b)
    expected_c = bytearray(original_c)
    expected_b[PAD:PAD + len(destination)] = wanted_dst
    expected_c[PAD:PAD + len(state)] = wanted_state
    return (result == status and bytes(a) == original_a
            and bytes(b) == bytes(expected_b)
            and bytes(c) == bytes(expected_c))


def state_for(src: int, dst: int, old: int, dest_old: int = 0,
              actual: int | None = None, reserved: bool = False) -> bytes:
    buf = bytearray([0x5b] * PAGE)
    buf[:HEADER] = b"\x00" * HEADER
    buf[0:2] = src.to_bytes(2, "little")
    buf[2:4] = dst.to_bytes(2, "little")
    buf[4:6] = bytes((old, dest_old))
    if src < SLOTS:
        buf[HEADER + src] = old if actual is None else actual
    if dst < SLOTS:
        buf[HEADER + dst] = dest_old
    if reserved:
        buf[11] = 1
    return bytes(buf)


def guarded(entry) -> str:
    if mmap.PAGESIZE != PAGE:
        return "SKIPPED_PAGE_SIZE_MISMATCH"
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    maps = []
    bases = []
    try:
        for _ in range(3):
            region = mmap.mmap(-1, 3 * PAGE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
            holder = (ctypes.c_ubyte * (3 * PAGE)).from_buffer(region)
            base = ctypes.addressof(holder)
            maps.append((region, holder))
            bases.append(base)
            assert libc.mprotect(base, PAGE, 0) == 0
            assert libc.mprotect(base + 2 * PAGE, PAGE, 0) == 0
        src, dst, state = (base + PAGE for base in bases)
        pattern = bytes(range(256)) * 16
        ctypes.memmove(src, pattern, PAGE)
        ctypes.memset(dst, 0x6D, PAGE)
        orig = state_for(0, SLOTS - 1, 2)
        ctypes.memmove(state, orig, PAGE)
        assert libc.mprotect(src, PAGE, mmap.PROT_READ) == 0
        assert entry(src, PAGE, dst, PAGE, state, PAGE) == 0
        assert ctypes.string_at(src, PAGE) == pattern
        assert ctypes.string_at(dst, PAGE) == pattern
        expected = bytearray(orig)
        expected[HEADER] = 1
        expected[HEADER + SLOTS - 1] = 1
        assert ctypes.string_at(state, PAGE) == bytes(expected)
        # Reject before touching read-only source or either writable region.
        assert entry(src, PAGE + 1, dst, PAGE, state, PAGE) == 1
        assert ctypes.string_at(dst, PAGE) == pattern
        assert ctypes.string_at(state, PAGE) == bytes(expected)
    finally:
        for base in bases:
            for offset in (0, PAGE, 2 * PAGE):
                assert libc.mprotect(base + offset, PAGE,
                                    mmap.PROT_READ | mmap.PROT_WRITE) == 0
        for i, (region, holder) in enumerate(maps):
            maps[i] = (region, None)
            del holder
            region.close()
    return "PASS"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    lib = ctypes.CDLL(str(args.library.resolve()))
    entry = lib.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint32
    rng = random.Random(20261120)
    cases = mismatches = 0
    pairs = [(0, 1), (1, 0), (25, 4079), (4079, 25), (200, 201)]
    for src, dst in pairs:
        for old in (0, 1, 2, 3, 254, 255):
            for dest_old in (0, 1, 2):
                for actual_delta in (0, 1):
                    state = state_for(src, dst, old, dest_old,
                                      actual=(old + actual_delta) & 255)
                    data = rng.randbytes(PAGE)
                    target = rng.randbytes(PAGE)
                    cases += 1
                    mismatches += not invoke(entry, data, target, state)
    for src, dst in [(0, 0), (4079, 4079), (4080, 1), (1, 4080),
                     (4095, 1), (1, 65535), (65535, 0)]:
        for old in (0, 2, 255):
            cases += 1
            mismatches += not invoke(entry, rng.randbytes(PAGE),
                                     rng.randbytes(PAGE),
                                     state_for(src, dst, old))
    for _ in range(120):
        src = rng.randrange(SLOTS)
        dst = rng.randrange(SLOTS)
        old = rng.randrange(256)
        state = state_for(src, dst, old,
                          dest_old=rng.choice((0, 0, 1, 2)),
                          actual=rng.choice((old, (old + 1) & 255)),
                          reserved=rng.randrange(9) == 0)
        data = rng.randbytes(PAGE)
        target = rng.randbytes(PAGE)
        variant = rng.randrange(7)
        if variant == 0:
            data = data[:rng.choice((0, 1, 4095))]
        if variant == 1:
            target = target[:rng.choice((0, 1, 4095, 4097))]
        if variant == 2:
            state = state[:rng.choice((0, 1, 4095, 4097))]
        cases += 1
        mismatches += not invoke(entry, data, target, state)
    if args.expect_unsafe:
        assert mismatches >= 40, (mismatches, cases)
        print(json.dumps({"cases": cases, "dishonest_detected": mismatches,
                          "negative_control": "PASS"}, sort_keys=True))
    else:
        assert mismatches == 0, (mismatches, cases)
        guard = guarded(entry)
        assert guard == "PASS", guard
        print(json.dumps({"cases": cases, "oracle_mismatches": mismatches,
                          "readonly_source_and_guard_pages": guard,
                          "status": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    main()
