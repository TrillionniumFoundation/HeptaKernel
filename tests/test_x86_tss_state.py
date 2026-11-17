#!/usr/bin/env python3
"""Independent 104-byte x86-64 TSS IST1 and IOPB native HIA oracle."""
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

def canonical(x):
    return bool(x) and x >> 48 == (0xffff if x & (1 << 47) else 0)

def oracle(req, state, reply_len):
    if reply_len < 16:
        return 1, None, bytes(state)
    if len(req) != 24:
        return 2, 0, bytes(state)
    if len(state) != 104:
        return 4, 0, bytes(state)
    top, old_ist, old_iomap = struct.unpack("<3Q", req)
    if not canonical(top) or top & 15 or old_iomap > 65535:
        return 6, 0, bytes(state)
    if struct.unpack_from("<Q", state, 36)[0] != old_ist or struct.unpack_from("<H", state, 102)[0] != old_iomap:
        return 9, 0, bytes(state)
    new = bytearray(state)
    struct.pack_into("<Q", new, 36, top)
    struct.pack_into("<H", new, 102, 104)
    return 0, top, bytes(new)

def campaign(lib):
    f = ctypes.CDLL(str(lib.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    stats = {"cases": 0, "admitted": 0, "rejected": 0}
    def check(req, tss, reply_len=16):
        r = ctypes.create_string_buffer(b"R"*32 + req + b"R"*32)
        s = ctypes.create_string_buffer(b"S"*32 + b"S"*reply_len + b"S"*32)
        t = ctypes.create_string_buffer(b"T"*32 + tss + b"T"*32)
        code, value, after = oracle(req, tss, reply_len)
        got = f(ctypes.addressof(r)+32, len(req), ctypes.addressof(s)+32, reply_len,
                ctypes.addressof(t)+32, len(tss))
        assert got == code, (got, code, req.hex())
        assert bytes(r) == b"R"*32 + req + b"R"*32 + b"\x00"
        assert bytes(t) == b"T"*32 + after + b"T"*32 + b"\x00"
        assert bytes(s)[:32] == b"S"*32
        assert bytes(s)[32+reply_len:] == b"S"*32 + b"\x00"
        if reply_len < 16:
            assert bytes(s)[32:32+reply_len] == b"S"*reply_len
        else:
            assert struct.unpack_from("<2Q", s, 32) == (code, value)
            assert bytes(s)[48:32+reply_len] == b"S"*(reply_len-16)
        stats["cases"] += 1
        stats["admitted" if code == 0 else "rejected"] += 1
    empty = bytes(104)
    for top in (0x1000, 0x1010, 0x8000, 0x7ffffffff000, 0xffff800000002000, 0xfffffffffffffff0):
        req = struct.pack("<3Q", top, 0, 0)
        check(req, empty)
        _, _, changed = oracle(req, empty, 16)
        check(req, changed)
        check(struct.pack("<3Q", top, top, 104), changed)
    for n in (0, 1, 8, 16, 23, 25, 32, 48):
        check(bytes(n), empty)
    for n in (0, 1, 15, 16, 17, 32):
        check(struct.pack("<3Q", 0x4000, 0, 0), empty, n)
    for n in (0, 1, 32, 103, 105, 128):
        check(struct.pack("<3Q", 0x4000, 0, 0), bytes(n))
    # Independently vary both stale expected fields without modifying the TSS.
    for stale in range(1, 257):
        check(struct.pack("<3Q", 0x4000, stale, 0), empty)
        check(struct.pack("<3Q", 0x4000, 0, stale), empty)
    rng = random.Random(0x7557)
    for i in range(1200):
        top = rng.choice((0, 1, 0x1000, 0x700f, 0xffff800000002000,
                          0xffffffff80002000, rng.getrandbits(64)))
        old_ist = rng.getrandbits(64) if i % 3 else 0
        old_map = rng.randrange(0x11000) if i % 4 else 0
        tss = bytearray(rng.randbytes(104))
        struct.pack_into("<Q", tss, 36, old_ist if i % 5 else 0)
        struct.pack_into("<H", tss, 102, (old_map & 65535) if i % 6 else 0)
        check(struct.pack("<3Q", top, old_ist, old_map), tss)
    assert stats["admitted"] >= 8 and stats["rejected"] > 1000, stats
    return {"schema": "heptakernel.native-tss-state.v1", "status": "PASS", **stats,
            "native_ist1_iomap": True, "native_ltr": False, "smp_atomic": False}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as exc:
            print("dishonest native HIA TSS-state writer rejected:", str(exc)[:160])
            return
        raise SystemExit("dishonest native HIA TSS writer unexpectedly passed")
    report = campaign(args.library)
    Path("build/x86-tss-state-report.json").write_text(json.dumps(report, indent=2)+"\n")
    print("native HIA TSS state:", report)

if __name__ == "__main__":
    main()
