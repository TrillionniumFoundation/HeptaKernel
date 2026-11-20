#!/usr/bin/env python3
"""Independent byte oracle for native HIA COW abort guarded by a live PTE read.

This tests a quiescent single-owner admission, not an atomic publication
protocol. The 8-byte readbuf should alias the *live* PTE supplied by a trusted
caller; arbitrary caller-controlled snapshots are not authenticated here.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import mmap
import random
from pathlib import Path

PAGE = 4096
SLOTS = PAGE - 16
PAD = 32
PADDR_MASK = 0x000F_FFFF_FFFF_F000
RESERVED_HIGH = 0x7FF0_0000_0000_0000
VALID_PTE = 0x8000_0000_0040_0005


def reference(pte: bytes, dest: bytes, state: bytes) -> tuple[int, bytes, bytes]:
    if len(pte) != 8:
        return 7, dest, state
    if len(state) != PAGE:
        return 2, dest, state
    if pte != state[8:16]:
        return 8, dest, state
    word = int.from_bytes(pte, "little")
    if ((word & 7) != 5 or (word & 0x100) != 0
            or (word & (1 << 63)) == 0
            or (word & RESERVED_HIGH) != 0
            or (word & PADDR_MASK) == 0):
        return 9, dest, state
    if len(dest) != PAGE:
        return 1, dest, state
    if state[6:8] != b"\x00\x00":
        return 3, dest, state
    src = int.from_bytes(state[0:2], "little")
    dst = int.from_bytes(state[2:4], "little")
    if src >= SLOTS or dst >= SLOTS or src == dst:
        return 4, dest, state
    src_old, dst_old = state[4], state[5]
    if state[16 + src] != src_old or state[16 + dst] != dst_old:
        return 5, dest, state
    if not 1 <= src_old <= 254 or dst_old != 1:
        return 6, dest, state
    updated = bytearray(state)
    updated[16 + src] = src_old + 1
    updated[16 + dst] = 0
    return 0, bytes(PAGE), bytes(updated)


def make_state(src: int, dst: int, src_old: int, dst_old: int = 1,
               *, actual_src: int | None = None,
               pte: int = VALID_PTE, bad_reserved: bool = False) -> bytes:
    state = bytearray([0x49] * PAGE)
    state[:16] = bytes(16)
    state[0:2] = src.to_bytes(2, "little")
    state[2:4] = dst.to_bytes(2, "little")
    state[4:6] = bytes((src_old, dst_old))
    state[8:16] = pte.to_bytes(8, "little")
    if bad_reserved:
        state[6] = 0xF1
    if src < SLOTS:
        state[16 + src] = src_old if actual_src is None else actual_src
    if dst < SLOTS:
        state[16 + dst] = dst_old
    return bytes(state)


def invoke(fn, pte: bytes, dest: bytes, state: bytes) -> bool:
    p = ctypes.create_string_buffer(bytes([0xA1]) * PAD + pte +
                                    bytes([0xA1]) * PAD)
    d = ctypes.create_string_buffer(bytes([0xB2]) * PAD + dest +
                                    bytes([0xB2]) * PAD)
    s = ctypes.create_string_buffer(bytes([0xC3]) * PAD + state +
                                    bytes([0xC3]) * PAD)
    before_p, before_d, before_s = bytes(p), bytes(d), bytes(s)
    actual = fn(ctypes.addressof(p) + PAD, len(pte),
                ctypes.addressof(d) + PAD, len(dest),
                ctypes.addressof(s) + PAD, len(state))
    code, want_dest, want_state = reference(pte, dest, state)
    want_d = bytearray(before_d)
    want_s = bytearray(before_s)
    want_d[PAD:PAD + len(dest)] = want_dest
    want_s[PAD:PAD + len(state)] = want_state
    return (actual == code and bytes(p) == before_p
            and bytes(d) == bytes(want_d)
            and bytes(s) == bytes(want_s))


def guard_pages(fn) -> str:
    if mmap.PAGESIZE != PAGE:
        raise AssertionError("4KiB guard page requirement not satisfied")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    maps = [mmap.mmap(-1, 3 * PAGE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
            for _ in range(3)]
    bases = [ctypes.addressof(ctypes.c_char.from_buffer(region)) for region in maps]
    try:
        for base in bases:
            assert libc.mprotect(base, PAGE, 0) == 0
            assert libc.mprotect(base + 2 * PAGE, PAGE, 0) == 0
        pte_addr = bases[0] + 2 * PAGE - 8
        dest_addr, state_addr = (base + PAGE for base in bases[1:])
        expected = make_state(0, 4079, 1)
        ctypes.memmove(pte_addr, VALID_PTE.to_bytes(8, "little"), 8)
        ctypes.memset(dest_addr, 0xDB, PAGE)
        ctypes.memmove(state_addr, expected, PAGE)
        assert libc.mprotect(bases[0] + PAGE, PAGE, mmap.PROT_READ) == 0
        assert fn(pte_addr, 8, dest_addr, PAGE, state_addr, PAGE) == 0
        assert ctypes.string_at(dest_addr, PAGE) == bytes(PAGE)
        wanted = bytearray(expected)
        wanted[16] = 2
        wanted[16 + 4079] = 0
        assert ctypes.string_at(state_addr, PAGE) == bytes(wanted)
        # An invalid length must be rejected without entering the guard page.
        assert fn(pte_addr, 9, dest_addr, PAGE, state_addr, PAGE) == 7
        assert ctypes.string_at(state_addr, PAGE) == bytes(wanted)
    finally:
        for base in bases:
            for offset in (0, PAGE, 2 * PAGE):
                assert libc.mprotect(base + offset, PAGE,
                                    mmap.PROT_READ | mmap.PROT_WRITE) == 0
        for region in maps:
            region.close()
    return "PASS"


def split_roundtrips(abort, split) -> int:
    split.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    split.restype = ctypes.c_uint32
    rng = random.Random(202611200425)
    checked = 0
    for src, dst in ((0, 4079), (4079, 0), (3, 5)):
        for original_count in (2, 3, 255):
            source = rng.randbytes(PAGE)
            srcbuf = ctypes.create_string_buffer(source)
            dest = ctypes.create_string_buffer(bytes([0xE2]) * PAGE)
            original = make_state(src, dst, original_count, 0, pte=0)
            state = ctypes.create_string_buffer(original)
            assert split(ctypes.addressof(srcbuf), PAGE,
                         ctypes.addressof(dest), PAGE,
                         ctypes.addressof(state), PAGE) == 0
            updated = bytearray(ctypes.string_at(state, PAGE))
            updated[4] = original_count - 1
            updated[5] = 1
            updated[8:16] = VALID_PTE.to_bytes(8, "little")
            ctypes.memmove(state, bytes(updated), PAGE)
            ptebuf = ctypes.create_string_buffer(VALID_PTE.to_bytes(8, "little"))
            assert abort(ctypes.addressof(ptebuf), 8,
                         ctypes.addressof(dest), PAGE,
                         ctypes.addressof(state), PAGE) == 0
            restored = bytearray(ctypes.string_at(state, PAGE))
            restored[4], restored[5] = original_count, 0
            restored[8:16] = bytes(8)
            assert bytes(restored) == original
            assert ctypes.string_at(srcbuf, PAGE) == source
            assert ctypes.string_at(dest, PAGE) == bytes(PAGE)
            checked += 1
    return checked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    parser.add_argument("--split-library", type=Path)
    args = parser.parse_args()
    entry = ctypes.CDLL(str(args.library.resolve())).f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint32
    rng = random.Random(20261120042)
    mismatches = positive = cases = 0
    for src, dst in ((0, 1), (1, 0), (25, 4079), (4079, 25), (200, 201)):
        for old in (0, 1, 2, 254, 255):
            for dst_old in (0, 1, 2):
                for stale in (False, True):
                    state = make_state(src, dst, old, dst_old,
                                       actual_src=(old + int(stale)) & 255)
                    data = rng.randbytes(PAGE)
                    pte = VALID_PTE.to_bytes(8, "little")
                    positive += reference(pte, data, state)[0] == 0
                    mismatches += not invoke(entry, pte, data, state)
                    cases += 1
    for mutant in (VALID_PTE ^ 2, VALID_PTE ^ 1, VALID_PTE ^ 4,
                   VALID_PTE ^ 0x100, VALID_PTE ^ (1 << 63),
                   VALID_PTE ^ (1 << 52), VALID_PTE ^ (1 << 59),
                   VALID_PTE ^ (1 << 60), 0x8000_0000_0000_0005):
        pte = mutant.to_bytes(8, "little")
        state = make_state(0, 1, 1, pte=mutant)
        mismatches += not invoke(entry, pte, rng.randbytes(PAGE), state)
        cases += 1
    for src, dst in ((0, 0), (4080, 1), (1, 4080), (65535, 1)):
        state = make_state(src, dst, 1)
        mismatches += not invoke(entry, VALID_PTE.to_bytes(8, "little"),
                                 rng.randbytes(PAGE), state)
        cases += 1
    for _ in range(160):
        src, dst = rng.randrange(SLOTS), rng.randrange(SLOTS)
        count = rng.randrange(256)
        state = make_state(src, dst, count, rng.choice((0, 1, 1, 2)),
                           bad_reserved=rng.randrange(11) == 0)
        data = rng.randbytes(PAGE)
        pte = VALID_PTE.to_bytes(8, "little")
        shape = rng.randrange(10)
        if shape == 0:
            pte = pte[:rng.choice((0, 1, 7))]
        elif shape == 1:
            pte = pte + b"z"
        elif shape == 2:
            pte = bytes([pte[0] ^ 0x20]) + pte[1:]
        elif shape == 3:
            data = data[:rng.choice((0, 1, 4095, 4097))]
        elif shape == 4:
            state = state[:rng.choice((0, 1, 4095, 4097))]
        positive += reference(pte, data, state)[0] == 0
        mismatches += not invoke(entry, pte, data, state)
        cases += 1
    if args.expect_unsafe:
        assert mismatches > 40, (cases, mismatches)
        print(json.dumps({"negative_control": "PASS", "cases": cases,
                          "dishonest_detected": mismatches}, sort_keys=True))
    else:
        assert mismatches == 0 and positive >= 10, (cases, positive, mismatches)
        guarded = guard_pages(entry)
        composed = 0
        if args.split_library:
            splitter = ctypes.CDLL(str(args.split_library.resolve())).f0
            composed = split_roundtrips(entry, splitter)
        print(json.dumps({"status": "PASS", "cases": cases, "positive": positive,
                          "oracle_mismatches": mismatches, "guard_pages": guarded,
                          "split_abort_round_trips": composed}, sort_keys=True))


if __name__ == "__main__":
    main()
