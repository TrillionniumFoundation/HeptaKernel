#!/usr/bin/env python3
"""Independent guarded HIA PML4E/PDPTE U/S gate oracle; not an atomic SMP CAS."""
from __future__ import annotations
import argparse
import ctypes
import json
import random
import struct
from pathlib import Path
PAGE = 4096
MAX = (1 << 64)-1
PHYS = ((1 << 52)-1) & ~4095
ALLOWED = PHYS | 0x23

def pack(slot,old,width=52):
    return struct.pack("<3Q",slot,old,width)

def oracle(req, table, reply_size=16):
    original = bytes(table)
    if reply_size < 16:
        return 1,None,original
    if len(req)!=24:
        return 2,0,original
    if len(table)!=PAGE:
        return 4,0,original
    slot,old,width = struct.unpack("<3Q",req)
    if width<32 or width>52:
        return 8,0,original
    if slot>=512:
        return 6,0,original
    addr = old & PHYS
    if old & ~ALLOWED or old & 3 != 3 or addr==0 or addr >= (1<<width):
        return 6,0,original
    if struct.unpack_from("<Q",original,slot*8)[0]!=old:
        return 9,0,original
    out=bytearray(original)
    new=old|4
    struct.pack_into("<Q",out,slot*8,new)
    return 0,new,bytes(out)

def campaign(lib):
    fn=ctypes.CDLL(str(lib.resolve())).f0
    fn.argtypes=[ctypes.c_void_p,ctypes.c_uint64]*3
    fn.restype=ctypes.c_uint32
    total=accept=deny=0
    def check(request,table,reply_size=16):
        nonlocal total,accept,deny
        inp=ctypes.create_string_buffer(b"\xa5"*32+request+b"\xa5"*32)
        rep=ctypes.create_string_buffer(b"\xb6"*(reply_size+64))
        mem=ctypes.create_string_buffer(b"\xc7"*32+table+b"\xc7"*32)
        inp0,rep0=bytes(inp),bytes(rep)
        rv=fn(ctypes.addressof(inp)+32,len(request),ctypes.addressof(rep)+32,
              reply_size,ctypes.addressof(mem)+32,len(table))
        status,value,expected=oracle(request,table,reply_size)
        assert bytes(inp)==inp0, "request corrupted"
        assert bytes(mem)[:32]==b"\xc7"*32 and bytes(mem)[32+len(table):32+len(table)+32]==b"\xc7"*32, "guard corrupted"
        assert bytes(mem)[32:32+len(table)]==expected, "table mutation outside contract"
        assert bytes(rep)[:32]==b"\xb6"*32 and bytes(rep)[32+reply_size:32+reply_size+32]==b"\xb6"*32, "reply guard corrupted"
        assert rv==status, (rv,status,request.hex())
        if reply_size<16:
            assert bytes(rep)==rep0
        else:
            assert struct.unpack_from("<2Q",rep,32)==(status,value)
            assert bytes(rep)[48:32+reply_size]==b"\xb6"*(reply_size-16)
        total+=1
        accept+=status==0
        deny+=status!=0
    rng=random.Random(0xA77105)
    valid=(0x1003,0x2023,0x3003,0x100023,0x200003,0x40000023)
    invalid=(0,3,0x1001,0x1002,0x1007,0x1083,
             0x8000000000001003,1<<52,0x100b,MAX,0x1003|64)
    for slot in (0,1,127,255,256,510,511):
        for old in valid+invalid:
            table=bytearray(rng.randbytes(PAGE))
            struct.pack_into("<Q",table,slot*8,old)
            for width in (32,36,48,52):
                check(pack(slot,old,width),bytes(table))
                check(pack(slot,old^32,width),bytes(table))
    for _ in range(1600):
        slot=rng.choice((0,1,511,512,MAX,rng.randrange(512)))
        old=rng.choice(valid+invalid+(rng.getrandbits(64),(1<<32)|3))
        data=bytearray(rng.randbytes(PAGE))
        if slot<512:
            struct.pack_into("<Q",data,slot*8,old)
        check(pack(slot,old if rng.randrange(5) else old^1,
                   rng.choice((31,32,36,48,52,53,MAX))),bytes(data))
    seed=bytearray(PAGE)
    struct.pack_into("<Q",seed,0,0x1003)
    for req in (b"",b"\0"*16,b"\0"*23,b"\0"*25,pack(0,0x1003)+b"\0"):
        check(req,bytes(seed))
    for n in (0,1,15,16,17,24,31):
        check(pack(0,0x1003),bytes(seed),n)
    for n in (0,1,8,4095,4097,8192):
        check(pack(0,0x1003),bytes(n))
    assert accept>=100 and deny>=600,(accept,deny)
    return {"schema":"heptakernel.upper-user.v1","status":"PASS",
            "cases":total,"commits":accept,"refusals":deny,
            "single_owner_only":True,"live_hardware_verified":False,
            "smp_atomicity_verified":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("library",type=Path)
    p.add_argument("--expect-unsafe",action="store_true")
    a=p.parse_args()
    if a.expect_unsafe:
        try:
            campaign(a.library)
        except AssertionError as error:
            print("dishonest native upper-table writer rejected:",str(error)[:250])
            return
        raise SystemExit("dishonest native upper-table writer passed")
    report=campaign(a.library)
    Path("build/x86-upper-user-report.json").write_text(json.dumps(report,indent=2)+"\n")
    print("HIA upper-level U/S gate:",report)
if __name__=="__main__":
    main()
