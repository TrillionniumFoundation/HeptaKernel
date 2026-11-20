#!/usr/bin/env python3
"""Independent byte oracle for single-owner HIA COW PTE private-frame switch."""
from __future__ import annotations
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

PAGE = 4096
NX = 1 << 63
PA = 0x000ffffffffff000
ALLOWED = PA | 0xfff | (0x7f << 52) | NX
CAPS = 52 | 256 | 512

def oracle(request: bytes, table: bytes, reply_size: int = 16):
    if reply_size < 16:
        return 1, None, table
    if len(request) != 32:
        return 2, 0, table
    if len(table) != PAGE:
        return 4, 0, table
    slot, old, new, caps = struct.unpack("<4Q", request)
    width = caps & 255
    if caps & ~1023 or not 32 <= width <= 52:
        return 8, 0, table
    oldpa, newpa = old & PA, new & PA
    cow_ok = ((old & 1) == 1 and not (old & 2) and (old & 4) == 4
              and not (old & 128) and not (old & 256)
              and (old & NX) == NX and not (old & 0x7800000000000000)
              and oldpa != 0 and newpa != 0 and oldpa != newpa
              and oldpa < 1 << width and newpa < 1 << width
              and new == (old - oldpa + newpa + 2) & ((1 << 64) - 1))
    if not cow_ok:
        return 6, 0, table
    if (new & ~ALLOWED or not (new & 1) or
            ((new & 2) and not (new & NX)) or
            ((new & 4) and (new & 256))):
        return 6, 0, table
    if ((new & NX) and not (caps & 256)) or ((new & 256) and not (caps & 512)):
        return 8, 0, table
    if slot >= 512:
        return 6, 0, table
    if struct.unpack_from("<Q", table, slot * 8)[0] != old:
        return 9, 0, table
    changed = bytearray(table)
    struct.pack_into("<Q", changed, slot * 8, new)
    return 0, new, bytes(changed)

def check(fn, request, table, reply_size=16):
    inp = ctypes.create_string_buffer(b"\xa5" * 32 + request + b"\xa5" * 32)
    out = ctypes.create_string_buffer(b"\xb6" * (reply_size + 64))
    mem = ctypes.create_string_buffer(b"\xc7" * 32 + table + b"\xc7" * 32)
    inp_before, out_before, mem_before = bytes(inp), bytes(out), bytes(mem)
    got = fn(ctypes.addressof(inp)+32, len(request),
             ctypes.addressof(out)+32, reply_size,
             ctypes.addressof(mem)+32, len(table))
    code, value, newtable = oracle(request, table, reply_size)
    wanted_mem = bytearray(mem_before)
    wanted_mem[32:32+len(table)] = newtable
    if code == 1:
        wanted_out = out_before
    else:
        wanted_out = bytearray(out_before)
        wanted_out[32:48] = struct.pack("<2Q", code, value)
    return (got == code and bytes(inp) == inp_before
            and bytes(mem) == bytes(wanted_mem) and bytes(out) == bytes(wanted_out))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--expect-unsafe", action="store_true")
    args = ap.parse_args()
    fn = ctypes.CDLL(str(args.library.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    rng = random.Random(20261120)
    cases = bad = positives = 0
    for slot in (0, 1, 255, 511, 512):
        for source in (0x402000, 0x700000, 0x2000000):
            for target in (0x601000, 0x800000, 0x2001000):
                for flags in (0x5, 0x25, 0x45, 0x65):
                    old = NX | source | flags
                    candidate = old - source + target + 2
                    for change in (0, 1, 2, 256, 512, 1 << 59):
                        request = struct.pack("<4Q", slot, old, candidate ^ change, CAPS)
                        table = bytearray(rng.randbytes(PAGE))
                        struct.pack_into("<Q", table, (slot % 512) * 8, old)
                        positives += oracle(request, bytes(table))[0] == 0
                        bad += not check(fn, request, bytes(table))
                        cases += 1
    for _ in range(1000):
        slot = rng.randrange(513)
        old = NX | rng.randrange(1, 256) * PAGE | rng.choice((5, 7, 1, 0x105, 0x205))
        target = rng.randrange(1, 512) * PAGE
        candidate = (old - (old & PA) + target + 2) & ((1 << 64) - 1)
        if rng.randrange(5) == 0:
            candidate ^= rng.choice((1, 2, 4, 128, 1 << 59))
        table = bytearray(rng.randbytes(PAGE))
        struct.pack_into("<Q", table, slot % 512 * 8, old)
        if rng.randrange(6) == 0:
            old ^= 1
        caps = rng.choice((CAPS, CAPS, 52, 32 | 256, 31 | 256))
        request = struct.pack("<4Q", slot, old, candidate, caps)
        bad += not check(fn, request, bytes(table))
        cases += 1
    # Failure paths must not mutate the writable reply or the page-table guard.
    for raw in (b"", b"\0"*24, b"\0"*33):
        bad += not check(fn, raw, bytes(PAGE))
        cases += 1
    for reply_len in (0, 1, 15):
        raw = struct.pack("<4Q", 0, NX | 0x402005, NX | 0x601007, CAPS)
        bad += not check(fn, raw, bytes(PAGE), reply_len)
        cases += 1
    for table_len in (0, 1, 4095, 4097):
        raw = struct.pack("<4Q", 0, NX | 0x402005, NX | 0x601007, CAPS)
        bad += not check(fn, raw, bytes(table_len))
        cases += 1
    if args.expect_unsafe:
        assert bad > 100, (bad, cases)
        print(json.dumps({"negative_control":"PASS","dishonest_detected":bad,"cases":cases},sort_keys=True))
    else:
        assert positives > 50, positives
        assert bad == 0, (bad,cases)
        print(json.dumps({"status":"PASS","cases":cases,"positive":positives,
                          "oracle_mismatches":bad},sort_keys=True))

if __name__ == "__main__":
    main()
