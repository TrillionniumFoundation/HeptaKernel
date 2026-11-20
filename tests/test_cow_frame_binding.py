#!/usr/bin/env python3
"""Independent byte-level oracle for genuine native HIA live PMM+PTE binding.

No HIA-written memory is accepted on the basis of a return code. This
policy only reads a caller-selected live PMM bitmap and live PTE; no CR3,
authority, synchronization or SMP claims follow from passing these tests.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

MAGIC = 0x314D4D504B484941
PAGE = 4096
MAX_PA = 1 << 52
ADDR = 0x000F_FFFF_FFFF_F000
HIGH_RESERVED = 0x7FF0_0000_0000_0000


def reference(req: bytes, pte: bytes, state: bytes) -> int:
    if len(req) != 48 or len(pte) != 8:
        return 1
    if len(state) < 64:
        return 2
    src, dst, expected, base, count, reserved = struct.unpack("<6Q", req)
    magic, actual_count, actual_base, actual_reserved, free = struct.unpack_from("<5Q", state)
    if (magic, actual_count, actual_base, actual_reserved) != (MAGIC, count, base, reserved):
        return 3
    if not (0 < count <= 65536 and reserved <= count and base % PAGE == 0
            and base < MAX_PA and count * PAGE <= MAX_PA - base
            and free <= count - reserved):
        return 4
    if not (src >= base and dst >= base and src != dst
            and (src - base) < count * PAGE and (dst - base) < count * PAGE
            and src % PAGE == dst % PAGE == 0):
        return 4
    observed = int.from_bytes(pte, "little")
    if not (observed == expected and observed & 0x107 == 5
            and observed & (1 << 63)
            and not observed & HIGH_RESERVED
            and (observed & ADDR) == src):
        return 5
    src_index, dst_index = (src - base) // PAGE, (dst - base) // PAGE
    if (src_index < reserved or dst_index < reserved
            or len(state) < 64 + (count + 7) // 8):
        return 6
    for slot in (src_index, dst_index):
        if not (state[64 + slot // 8] & (1 << (slot % 8))):
            return 6
    return 0


def payload(*, src_index=1, dst_index=2, count=17, reserved=1,
            base=0x600000, bitmap=0b00000111,
            flags=0x8000000000000005):
    state = bytearray(8192)
    state[:40] = struct.pack("<5Q", MAGIC, count, base, reserved, count-reserved-2)
    state[64] = bitmap
    src = base + src_index * PAGE
    dst = base + dst_index * PAGE
    pte = (src | flags).to_bytes(8, "little")
    req = struct.pack("<6Q", src, dst, int.from_bytes(pte, "little"),
                      base, count, reserved)
    return req, pte, bytes(state)


def entry(path):
    fn = ctypes.CDLL(str(Path(path).resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    return fn


def invoke(fn, req, pte, state):
    # Real canaries surround every buffer, and every byte must remain intact.
    pad = 32
    regions = []
    for data, sentinel in ((req, 0xA3), (pte, 0xB4), (state, 0xC5)):
        storage = (ctypes.c_ubyte * (len(data) + 2 * pad))()
        ctypes.memset(ctypes.addressof(storage), sentinel, len(storage))
        if data:
            ctypes.memmove(ctypes.addressof(storage) + pad, data, len(data))
        regions.append((storage, bytes(storage), len(data)))
    args = []
    for buf, before, length in regions:
        args.extend((ctypes.addressof(buf) + pad, length))
    got = fn(*args)
    for buf, before, length in regions:
        assert bytes(buf) == before, ("unexpected mutation", length, got)
    expected = reference(req, pte, state)
    return got, expected


def main():
    p = argparse.ArgumentParser()
    p.add_argument("library")
    p.add_argument("--expect-unsafe", action="store_true")
    args = p.parse_args()
    fn = entry(args.library)
    rng = random.Random(0xC0BABA)
    base = payload()
    samples = [base]
    req, pte, state = base
    # Actual PMM owner transitions and PTE provenance must affect the result.
    for replacement in (0, 1, 3, 4, 0xFF):
        owner = bytearray(state)
        owner[64] = replacement
        samples.append((req, pte, bytes(owner)))
    for slot in (0, 8, 16, 24, 32):
        for alternative in (0, 1, 0xFFFF_FFFF_FFFF_FFFF):
            owner = bytearray(state)
            struct.pack_into("<Q", owner, slot, alternative)
            samples.append((req, pte, bytes(owner)))
    for slot in (0, 8, 16, 24, 32, 40):
        for alternative in (0, 1, 0xFFFF_FFFF_FFFF_FFFF):
            wire = bytearray(req)
            struct.pack_into("<Q", wire, slot, alternative)
            samples.append((bytes(wire), pte, state))
    for word in (0, 1, 0x8000000000601007, 0x8000000000600005,
                 0x8000000000602005, 0x8000000000601105,
                 0x800000000060110D, 0x800000000060100D,
                 0x0000000000601005, 0x8000000000601105 | (1 << 55)):
        samples.append((req, word.to_bytes(8, "little"), state))
    for n in (0, 7, 8, 9, 24, 47, 49):
        samples.append((req[:n], pte, state))
    for n in (0, 1, 7, 9):
        samples.append((req, pte[:n], state))
    for n in (0, 31, 63, 64, 65, 66):
        samples.append((req, pte, state[:n]))
    # Stable deterministic randomized mutations with an independent oracle.
    for _ in range(640):
        r, pte_mut, owner = payload()
        wire, leaf, table = bytearray(r), bytearray(pte_mut), bytearray(owner)
        field = rng.randrange(7)
        if field == 0:
            offset = rng.randrange(len(wire))
            wire[offset] ^= 1 << rng.randrange(8)
        elif field == 1:
            offset = rng.randrange(len(leaf))
            leaf[offset] ^= 1 << rng.randrange(8)
        elif field == 2:
            offset = rng.choice((0, 8, 16, 24, 32, 64))
            table[offset] ^= 1 << rng.randrange(8)
        elif field == 3:
            table[64] = rng.randrange(256)
        elif field == 4:
            wire[16:24] = rng.getrandbits(64).to_bytes(8, "little")
        elif field == 5:
            wire[0:8] = rng.getrandbits(64).to_bytes(8, "little")
        else:
            wire[8:16] = rng.getrandbits(64).to_bytes(8, "little")
        samples.append((bytes(wire), bytes(leaf), bytes(table)))
    ok = 0
    mutations_caught = 0
    accepted = 0
    for index, (wire, leaf, owner) in enumerate(samples):
        got, expected = invoke(fn, wire, leaf, owner)
        if args.expect_unsafe:
            if got != expected:
                mutations_caught += 1
        else:
            assert got == expected, (index, got, expected)
            if got == 0:
                accepted += 1
            ok += 1
    if args.expect_unsafe:
        assert mutations_caught >= 100, mutations_caught
    else:
        assert accepted > 0
    report = {"schema": "heptakernel.cow-frame-binding.v1",
              "cases": len(samples), "matches": ok, "positives": accepted,
              "dishonest_detections": mutations_caught,
              "status": "DISHONEST_DETECTED" if args.expect_unsafe else "PASS"}
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
