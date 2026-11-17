#!/usr/bin/env python3
"""Independent IDT descriptor encoding and exclusive-write native HIA oracle."""
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

MASK = (1 << 64) - 1

def canonical(address):
    return bool(address) and (address >> 48 == (0xffff if (address >> 47) & 1 else 0))

def encode(addr):
    low = (addr & 0xffff) | (8 << 16) | (0x8e << 40) | (((addr >> 16) & 0xffff) << 48)
    return low, addr >> 32

def oracle(request, table, reply_size):
    if reply_size < 16:
        return 1, None, bytes(table)
    if len(request) != 32:
        return 2, 0, bytes(table)
    if len(table) != 4096:
        return 4, 0, bytes(table)
    vector, addr, expected_low, expected_high = struct.unpack("<4Q", request)
    if vector >= 256 or not canonical(addr):
        return 6, 0, bytes(table)
    offset = vector * 16
    if struct.unpack_from("<2Q", table, offset) != (expected_low, expected_high):
        return 9, 0, bytes(table)
    updated = bytearray(table)
    low, high = encode(addr)
    struct.pack_into("<2Q", updated, offset, low, high)
    return 0, low, bytes(updated)

def campaign(library):
    f = ctypes.CDLL(str(library.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    counts = dict(cases=0, admitted=0, rejected=0)
    def check(raw, table, reply_size=16):
        req = ctypes.create_string_buffer(b"R" * 32 + raw + b"R" * 32)
        rep = ctypes.create_string_buffer(b"S" * (reply_size + 64))
        tab = ctypes.create_string_buffer(b"T" * 32 + table + b"T" * 32)
        original_req, original_tab = bytes(req), bytes(tab)
        expected_status, expected_value, expected_table = oracle(raw, table, reply_size)
        result = f(ctypes.addressof(req) + 32, len(raw),
                   ctypes.addressof(rep) + 32, reply_size,
                   ctypes.addressof(tab) + 32, len(table))
        assert result == expected_status, (result, expected_status, raw.hex())
        assert bytes(req) == original_req, "request overwritten"
        assert bytes(tab)[:32] == original_tab[:32], "table prefix overwritten"
        assert bytes(tab)[32 + len(table):] == original_tab[32 + len(table):], "table suffix overwritten"
        assert bytes(tab)[32:32 + len(table)] == expected_table, "table changed incorrectly"
        assert bytes(rep)[:32] == b"S" * 32, "reply prefix overwritten"
        assert bytes(rep)[32 + reply_size:32 + reply_size + 32] == b"S" * 32, "reply suffix overwritten"
        if reply_size < 16:
            assert bytes(rep) == b"S" * (reply_size + 64) + bytes([0]), "short reply changed"
        else:
            assert struct.unpack_from("<2Q", rep, 32) == (expected_status, expected_value)
            assert bytes(rep)[48:32 + reply_size] == b"S" * (reply_size - 16)
        counts["cases"] += 1
        counts["admitted" if expected_status == 0 else "rejected"] += 1

    # All 256 vectors are installed in one real 4-KiB IDT, then deliberately retried.
    table = bytearray(4096)
    for vector in range(256):
        addr = 0xffffffff80001000 + vector * 16
        old = struct.unpack_from("<2Q", table, vector * 16)
        raw = struct.pack("<4Q", vector, addr, *old)
        check(raw, bytes(table))
        _, _, changed = oracle(raw, table, 16)
        table[:] = changed
        check(raw, bytes(table))    # expected-old mismatch must not rewrite
    assert all(struct.unpack_from("<2Q", table, i * 16) == encode(0xffffffff80001000 + i * 16) for i in range(256))
    # Independently exercise noncanonical upper half and the exact boundaries.
    for addr in (0, 1, 0x7fffffffffff, 0x800000000000,
                 0xffff7fffffffffff, 0xffff800000000000, MASK):
        for vector in (0, 14, 255, 256, MASK):
            check(struct.pack("<4Q", vector, addr, 0, 0), bytes(4096))
    for reply_size in (0, 1, 7, 15, 16, 17, 32):
        check(struct.pack("<4Q", 14, 0xffffffff80004000, 0, 0), bytes(4096), reply_size)
    for request_size in (0, 1, 16, 24, 31, 33, 72):
        check(bytes(request_size), bytes(4096))
    for table_size in (0, 1, 16, 4095, 4097, 8192):
        check(struct.pack("<4Q", 14, 0xffffffff80004000, 0, 0), bytes(table_size))
    rng = random.Random(0x1D714)
    for k in range(1600):
        vector = rng.randrange(260)
        addr = rng.choice((0, MASK, 0x800000000000, 0x00007fffffff0000,
                           0xffff800000004000, rng.getrandbits(64)))
        old = rng.choice((0, MASK, rng.getrandbits(64)))
        table = bytearray(4096)
        if k % 3 == 0 and vector < 256:
            struct.pack_into("<2Q", table, 16 * vector, old, rng.getrandbits(64))
        check(struct.pack("<4Q", vector, addr, old, 0), bytes(table))
    assert counts["admitted"] >= 250 and counts["rejected"] >= 1000, counts
    return {"status": "PASS", **counts, "real_hardware_idt_verified": False,
            "hia_native_privileged_lidt": False, "concurrent_atomicity_verified": False}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("library", type=Path)
    p.add_argument("--expect-unsafe", action="store_true")
    a = p.parse_args()
    if a.expect_unsafe:
        try:
            campaign(a.library)
        except AssertionError as exc:
            print("dishonest native HIA IDT installer refused by oracle:", str(exc)[:220])
            return
        raise SystemExit("dishonest installer unexpectedly passed")
    result = campaign(a.library)
    Path("build/x86-idt-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print("native HIA IDT gate:", result)
if __name__ == "__main__":
    main()
