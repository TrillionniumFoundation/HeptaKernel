#!/usr/bin/env python3
"""Independent two-selector long-mode CPL3 GDT oracle for genuine native HIA."""
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

CODE = 0x00affa000000ffff
DATA = 0x00cff2000000ffff
PREFIX = struct.pack("<6Q", 0, 0x00af9a000000ffff,
                     0x00cf92000000ffff, 0x00cf9a000000ffff, 0, 0)

def oracle(raw, table, reply_size):
    if reply_size < 16:
        return 1, None, bytes(table)
    if len(raw) != 16:
        return 2, 0, bytes(table)
    if len(table) != 64:
        return 4, 0, bytes(table)
    old_code, old_data = struct.unpack("<2Q", raw)
    if struct.unpack_from("<2Q", table, 48) != (old_code, old_data):
        return 9, 0, bytes(table)
    out = bytearray(table)
    struct.pack_into("<2Q", out, 48, CODE, DATA)
    return 0, CODE, bytes(out)

def campaign(library):
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    counts = dict(cases=0, admitted=0, rejected=0)
    def check(raw, table, reply_size=16):
        rq = ctypes.create_string_buffer(b"R"*32 + raw + b"R"*32)
        rp = ctypes.create_string_buffer(b"S"*(reply_size + 64))
        gd = ctypes.create_string_buffer(b"G"*32 + table + b"G"*32)
        code, word, expected = oracle(raw, table, reply_size)
        status = native(ctypes.addressof(rq)+32, len(raw),
                        ctypes.addressof(rp)+32, reply_size,
                        ctypes.addressof(gd)+32, len(table))
        assert status == code, (status, code, raw.hex())
        assert bytes(rq) == b"R"*32 + raw + b"R"*32 + b"\0"
        assert bytes(gd)[:32] == b"G"*32
        assert bytes(gd)[32:32+len(table)] == expected
        assert bytes(gd)[32+len(table):] == b"G"*32 + b"\0"
        assert bytes(rp)[:32] == b"S"*32
        assert bytes(rp)[32+reply_size:32+reply_size+32] == b"S"*32
        if reply_size < 16:
            assert bytes(rp) == b"S"*(reply_size+64) + b"\0"
        else:
            assert struct.unpack_from("<2Q", rp, 32) == (code, word)
            assert bytes(rp)[48:32+reply_size] == b"S"*(reply_size-16)
        counts["cases"] += 1
        counts["admitted" if code == 0 else "rejected"] += 1
    empty = PREFIX + bytes(16)
    for old in ((0, 0), (1, 0), (0, 1), (CODE, DATA)):
        check(struct.pack("<2Q", *old), empty)
    check(struct.pack("<2Q", 0, 0), empty)
    check(struct.pack("<2Q", CODE, DATA), PREFIX + struct.pack("<2Q", CODE, DATA))
    for n in (0,1,7,8,15,17,24,32,40):
        check(bytes(n), empty)
    for n in (0,1,7,15,16,17,32):
        check(bytes(16), empty, n)
    for n in (0,8,15,48,55,63,65,80):
        check(bytes(16), bytes(n))
    rng = random.Random(0x6383)
    for i in range(1500):
        current = (rng.choice((0, CODE, rng.getrandbits(64))),
                   rng.choice((0, DATA, rng.getrandbits(64))))
        expected = (current[0] if i % 3 else rng.getrandbits(64),
                    current[1] if i % 5 else rng.getrandbits(64))
        table = PREFIX + struct.pack("<2Q", *current)
        check(struct.pack("<2Q", *expected), table)
    assert counts["admitted"] >= 100 and counts["rejected"] >= 500, counts
    return {"schema":"heptakernel.native-user-gdt.v1","status":"PASS",**counts,
            "native_hia_user_descriptors":True,"iretq_native":False,
            "smp_atomicity":False}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library",type=Path)
    ap.add_argument("--expect-unsafe",action="store_true")
    args = ap.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as exc:
            print("dishonest native HIA user GDT control rejected:", str(exc)[:160])
            return
        raise SystemExit("dishonest native HIA control unexpectedly passed")
    report = campaign(args.library)
    Path("build/x86-user-gdt-report.json").write_text(json.dumps(report,indent=2)+"\n")
    print("native HIA user GDT:", report)

if __name__ == "__main__":
    main()
