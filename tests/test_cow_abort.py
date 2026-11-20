#!/usr/bin/env python3
"""Independent byte oracle for HIA COW abort before PTE publication.

Only caller-owned, quiescent, disjoint writable capabilities are admitted.
The PTE must still map the shared source, checked by the caller; this does
not provide a transaction, privilege backend, or atomic SMP reclamation.
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


def oracle(request: bytes, destination: bytes, state: bytes) -> tuple[int, bytes, bytes]:
    if len(request) != 0:
        return 7, destination, state
    if len(destination) != PAGE:
        return 1, destination, state
    if len(state) != PAGE:
        return 2, destination, state
    if any(state[6:HEADER]):
        return 3, destination, state
    src = int.from_bytes(state[0:2], "little")
    dst = int.from_bytes(state[2:4], "little")
    if src >= SLOTS or dst >= SLOTS or src == dst:
        return 4, destination, state
    expected_src, expected_dst = state[4:6]
    if (state[HEADER + src] != expected_src or
            state[HEADER + dst] != expected_dst):
        return 5, destination, state
    if not 1 <= expected_src <= 254 or expected_dst != 1:
        return 6, destination, state
    updated = bytearray(state)
    updated[HEADER + src] = expected_src + 1
    updated[HEADER + dst] = 0
    return 0, bytes(PAGE), bytes(updated)


def state_for(src: int, dst: int, old: int, dest_old: int = 1,
              actual: int | None = None, reserved: bool = False) -> bytes:
    state = bytearray([0x51] * PAGE)
    state[:HEADER] = bytes(HEADER)
    state[0:2] = src.to_bytes(2, "little")
    state[2:4] = dst.to_bytes(2, "little")
    state[4:6] = bytes((old, dest_old))
    if src < SLOTS:
        state[HEADER + src] = old if actual is None else actual
    if dst < SLOTS:
        state[HEADER + dst] = dest_old
    if reserved:
        state[11] = 0x7B
    return bytes(state)


def invoke(entry, destination: bytes, state: bytes, request: bytes = b"") -> bool:
    r = ctypes.create_string_buffer(bytes([0xC4]) * PAD +
                                    request + bytes([0xC4]) * PAD)
    d = ctypes.create_string_buffer(bytes([0xA5]) * PAD +
                                    destination + bytes([0xA5]) * PAD)
    s = ctypes.create_string_buffer(bytes([0xB6]) * PAD +
                                    state + bytes([0xB6]) * PAD)
    before_r, before_d, before_s = bytes(r), bytes(d), bytes(s)
    result = entry(ctypes.addressof(r) + PAD, len(request),
                   ctypes.addressof(d) + PAD, len(destination),
                   ctypes.addressof(s) + PAD, len(state))
    status, expected_d, expected_s = oracle(request, destination, state)
    wanted_d, wanted_s = bytearray(before_d), bytearray(before_s)
    wanted_d[PAD:PAD + len(destination)] = expected_d
    wanted_s[PAD:PAD + len(state)] = expected_s
    return (result == status and bytes(r) == before_r and
            bytes(d) == bytes(wanted_d) and
            bytes(s) == bytes(wanted_s))


def guarded(entry) -> str:
    if mmap.PAGESIZE != PAGE:
        raise AssertionError("Guard-page test requires 4KiB host pages")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    maps = [mmap.mmap(-1, 3 * PAGE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
            for _ in range(2)]
    bases = [ctypes.addressof(ctypes.c_char.from_buffer(r)) for r in maps]
    try:
        for base in bases:
            assert libc.mprotect(base, PAGE, 0) == 0
            assert libc.mprotect(base + 2 * PAGE, PAGE, 0) == 0
        destination, state = (base + PAGE for base in bases)
        ctypes.memset(destination, 0xEA, PAGE)
        initial = state_for(0, SLOTS - 1, 1)
        ctypes.memmove(state, initial, PAGE)
        req = ctypes.create_string_buffer(b"\x00")
        assert entry(ctypes.addressof(req), 0, destination, PAGE, state, PAGE) == 0
        assert ctypes.string_at(destination, PAGE) == bytes(PAGE)
        wanted = bytearray(initial)
        wanted[HEADER] = 2
        wanted[HEADER + SLOTS - 1] = 0
        assert ctypes.string_at(state, PAGE) == bytes(wanted)
        assert entry(ctypes.addressof(req), 0, destination, PAGE + 1, state, PAGE) == 1
        assert ctypes.string_at(state, PAGE) == bytes(wanted)
    finally:
        for base in bases:
            for offset in (0, PAGE, 2 * PAGE):
                assert libc.mprotect(base + offset, PAGE,
                                    mmap.PROT_READ | mmap.PROT_WRITE) == 0
        for r in maps:
            r.close()
    return "PASS"


def composition(abort, split) -> int:
    split.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    split.restype = ctypes.c_uint32
    rng = random.Random(2026112001)
    passed = 0
    for src_slot, dst_slot in ((0, 4079), (4079, 0), (17, 22)):
        for old in (2, 3, 127, 255):
            source = bytes(rng.randbytes(PAGE))
            src_buf = ctypes.create_string_buffer(source)
            destination = ctypes.create_string_buffer(bytes([0xFA]) * PAGE)
            original = state_for(src_slot, dst_slot, old, 0)
            state = ctypes.create_string_buffer(original)
            assert split(ctypes.addressof(src_buf), PAGE,
                         ctypes.addressof(destination), PAGE,
                         ctypes.addressof(state), PAGE) == 0
            snapshot = bytearray(ctypes.string_at(state, PAGE))
            snapshot[4] = old - 1
            snapshot[5] = 1
            ctypes.memmove(state, bytes(snapshot), PAGE)
            req = ctypes.create_string_buffer(b"\x00")
            assert abort(ctypes.addressof(req), 0,
                         ctypes.addressof(destination), PAGE,
                         ctypes.addressof(state), PAGE) == 0
            restored = bytearray(ctypes.string_at(state, PAGE))
            restored[4] = old
            restored[5] = 0
            assert bytes(restored) == original
            assert ctypes.string_at(src_buf, PAGE) == source
            assert ctypes.string_at(destination, PAGE) == bytes(PAGE)
            passed += 1
    return passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    parser.add_argument("--split-library", type=Path)
    args = parser.parse_args()
    abort = ctypes.CDLL(str(args.library.resolve())).f0
    abort.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    abort.restype = ctypes.c_uint32
    rng = random.Random(20261120)
    cases = mismatches = accepted = 0
    for src, dst in ((0, 1), (1, 0), (25, 4079), (4079, 25), (201, 202)):
        for old in (0, 1, 2, 254, 255):
            for dest_old in (0, 1, 2):
                for delta in (0, 1):
                    state = state_for(src, dst, old, dest_old,
                                      actual=(old + delta) & 255)
                    data = rng.randbytes(PAGE)
                    accepted += oracle(b"", data, state)[0] == 0
                    mismatches += not invoke(abort, data, state)
                    cases += 1
    for src, dst in ((0, 0), (4080, 1), (1, 4080), (65535, 1), (1, 65535)):
        for old in (1, 2, 254):
            state = state_for(src, dst, old)
            mismatches += not invoke(abort, rng.randbytes(PAGE), state)
            cases += 1
    for _ in range(160):
        src, dst = rng.randrange(SLOTS), rng.randrange(SLOTS)
        state = state_for(src, dst, rng.randrange(256),
                          dest_old=rng.choice((0, 1, 1, 2)),
                          reserved=rng.randrange(13) == 0)
        data = rng.randbytes(PAGE)
        shape = rng.randrange(8)
        if shape == 0:
            data = data[:rng.choice((0, 4095, 4097))]
        elif shape == 1:
            state = state[:rng.choice((0, 4095, 4097))]
        accepted += oracle(data, state)[0] == 0
        mismatches += not invoke(abort, data, state)
        cases += 1
    for payload in (b"x", b"\x00" * 16):
        mismatches += not invoke(abort, rng.randbytes(PAGE),
                                 state_for(0, 1, 1), request=payload)
        cases += 1
    if args.expect_unsafe:
        assert mismatches > 30, (cases, mismatches)
        print(json.dumps({"negative_control": "PASS", "cases": cases,
                          "dishonest_detected": mismatches}, sort_keys=True))
    else:
        assert mismatches == 0 and accepted >= 10, (cases, accepted, mismatches)
        guard = guarded(abort)
        composed = 0
        if args.split_library:
            split = ctypes.CDLL(str(args.split_library.resolve())).f0
            composed = composition(abort, split)
        print(json.dumps({"status": "PASS", "cases": cases,
                          "positive": accepted, "oracle_mismatches": mismatches,
                          "guard_pages": guard, "split_abort_round_trips": composed},
                         sort_keys=True))


if __name__ == "__main__":
    main()
