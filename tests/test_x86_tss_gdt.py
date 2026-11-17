#!/usr/bin/env python3
"""Independent x86-64 104-byte TSS descriptor oracle for genuine native HIA."""
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path

MASK = (1 << 64) - 1
GDT_PREFIX = struct.pack("<4Q", 0, 0x00af9a000000ffff,
                         0x00cf92000000ffff, 0x00cf9a000000ffff)
def canonical(a):
    return bool(a) and (a >> 48 == (0xffff if a & (1 << 47) else 0))
def encode(base):
    low = 0x0000890000000067 | ((base & 0xffffff) << 16) | (((base >> 24) & 255) << 56)
    return low, base >> 32
def oracle(raw, table, reply_size):
    if reply_size < 16:
        return 1, None, bytes(table)
    if len(raw) != 32:
        return 2, 0, bytes(table)
    if len(table) != 48:
        return 4, 0, bytes(table)
    base, limit, oldlo, oldhi = struct.unpack("<4Q", raw)
    if not canonical(base) or base & 15 or limit != 103:
        return 6, 0, bytes(table)
    if struct.unpack_from("<2Q", table, 32) != (oldlo, oldhi):
        return 9, 0, bytes(table)
    result = bytearray(table)
    low, high = encode(base)
    struct.pack_into("<2Q", result, 32, low, high)
    return 0, low, bytes(result)
def campaign(library):
    f = ctypes.CDLL(str(library.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    counts = dict(cases=0, admitted=0, rejected=0)
    def check(raw, table, reply_size=16):
        request = ctypes.create_string_buffer(b"R"*32 + raw + b"R"*32)
        reply = ctypes.create_string_buffer(b"S"*(reply_size + 64))
        gdt = ctypes.create_string_buffer(b"G"*32 + table + b"G"*32)
        before = bytes(gdt)
        expected_code, expected_low, expected_gdt = oracle(raw, table, reply_size)
        status = f(ctypes.addressof(request)+32, len(raw),
                   ctypes.addressof(reply)+32, reply_size,
                   ctypes.addressof(gdt)+32, len(table))
        assert status == expected_code, (status,expected_code,raw.hex())
        assert bytes(request) == b"R"*32 + raw + b"R"*32 + b"\0"
        assert bytes(gdt)[:32] == before[:32], "table prefix mutated"
        assert bytes(gdt)[32:32+len(table)] == expected_gdt, "unexpected GDT mutation"
        assert bytes(gdt)[32+len(table):] == before[32+len(table):], "table suffix mutated"
        assert bytes(reply)[:32] == b"S"*32
        assert bytes(reply)[32+reply_size:32+reply_size+32] == b"S"*32
        if reply_size < 16:
            assert bytes(reply) == b"S"*(reply_size+64) + b"\0"
        else:
            assert struct.unpack_from("<2Q",reply,32) == (expected_code,expected_low)
            assert bytes(reply)[48:32+reply_size] == b"S"*(reply_size-16)
        counts["cases"]+=1
        counts["admitted" if expected_code==0 else "rejected"]+=1

    gdt = GDT_PREFIX + bytes(16)
    for base in (0x1000,0x1010,0x7000,0x1234000,0x7fffffffe000,
                 0xffff800000001000,0xffffffff80002000,0xfffffffffffffff0):
        raw=struct.pack("<4Q",base,103,0,0)
        check(raw,gdt)
        _,_,changed=oracle(raw,gdt,16)
        check(raw,changed)
    for n in (0,1,8,15,16,31,33,40,64):
        check(bytes(n),gdt)
    for n in (0,1,7,15,16,17,32):
        check(struct.pack("<4Q",0x1234000,103,0,0),gdt,n)
    for n in (0,8,15,32,47,49,80):
        check(struct.pack("<4Q",0x1234000,103,0,0),bytes(n))
    for addr in (0,1,0x100f,0x800000000000,0xffff7fffffffffff,
                 0xffff800000000001,0x7ffffffffff1,MASK):
        for limit in (0,103,104,65535,MASK):
            check(struct.pack("<4Q",addr,limit,0,0),gdt)
    rng=random.Random(0x7555)
    for i in range(1200):
        base=rng.choice((0,0x1000,0x1234000,0x700f,0xffff800000001000,
                         0xffffffff80002000,rng.getrandbits(64)))
        limit=rng.choice((0,103,104,rng.randrange(512)))
        oldlo=rng.choice((0,1,rng.getrandbits(64)))
        oldhi=rng.choice((0,1,rng.getrandbits(64)))
        table=GDT_PREFIX+struct.pack("<2Q",oldlo if i%3 else 0,oldhi if i%5 else 0)
        check(struct.pack("<4Q",base,limit,oldlo,oldhi),table)
    assert counts["admitted"] > 70 and counts["rejected"] > 1000,counts
    return {"schema":"heptakernel.native-tss-gdt.v1","status":"PASS",**counts,
            "tss_descriptor_native":True,"ltr_native":False,"smp_atomicity":False}
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("library",type=Path)
    ap.add_argument("--expect-unsafe",action="store_true")
    args=ap.parse_args()
    if args.expect_unsafe:
        try:
            campaign(args.library)
        except AssertionError as e:
            print("dishonest native HIA TSS writer rejected:",str(e)[:160])
            return
        raise SystemExit("dishonest HIA TSS implementation unexpectedly passed")
    report=campaign(args.library)
    Path("build/x86-tss-gdt-report.json").write_text(json.dumps(report,indent=2)+"\n")
    print("native HIA TSS GDT:",report)
if __name__ == "__main__":
    main()
