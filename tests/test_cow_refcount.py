#!/usr/bin/env python3
"""Native HIA COW refcount table tests against an independent byte oracle.

The table is a bounded single-owner model, not an atomic Linux page reference.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import mmap
import random
from pathlib import Path

SIZE = 4096
CANARY = 32

def expected(req, receipt_len, table_len, before):
    if receipt_len != 16:
        return 1, before, None
    if len(req) != 16:
        return 2, before, None
    if table_len != SIZE:
        return 3, before, None
    slot = int.from_bytes(req[:2], "little")
    action, old = req[2], req[3]
    if any(req[4:]):
        return 8, before, None
    if slot >= SIZE:
        return 4, before, None
    if action not in (1, 2, 3):
        return 5, before, None
    if before[slot] != old:
        return 7, before, None
    if action == 1 and 1 <= old <= 254:
        new = old + 1
    elif action == 2 and old >= 2:
        new = old - 1
    elif action == 3 and old == 1:
        new = 0
    else:
        return 6, before, None
    result = bytearray(before)
    result[slot] = new
    return 0, bytes(result), bytes(8) + bytes([new]) + bytes(7)

def invoke(entry, req, count_bytes, receipt_len=16):
    req_buf = ctypes.create_string_buffer(b"\xa5"*CANARY + req + b"\xa5"*CANARY)
    rec_buf = ctypes.create_string_buffer(b"\xb6"*(receipt_len+2*CANARY))
    tab_buf = ctypes.create_string_buffer(b"\xc7"*CANARY + count_bytes + b"\xc7"*CANARY)
    before_req, before_rec, before_tab = bytes(req_buf), bytes(rec_buf), bytes(tab_buf)
    ret = entry(ctypes.addressof(req_buf)+CANARY,len(req),
                ctypes.addressof(rec_buf)+CANARY,receipt_len,
                ctypes.addressof(tab_buf)+CANARY,len(count_bytes))
    code, table_after, receipt_after = expected(req, receipt_len,len(count_bytes),count_bytes)
    wanted_rec = before_rec if receipt_after is None else (b"\xb6"*CANARY + receipt_after + b"\xb6"*CANARY + b"\0")
    wanted_tab = b"\xc7"*CANARY + table_after + b"\xc7"*CANARY + b"\0"
    return ret == code and bytes(req_buf) == before_req and bytes(rec_buf) == wanted_rec and bytes(tab_buf) == wanted_tab

def guarded(entry):
    if mmap.PAGESIZE != SIZE:
        return "SKIPPED_PAGE_SIZE_MISMATCH"
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = (ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    area=mmap.mmap(-1,3*SIZE,prot=mmap.PROT_READ|mmap.PROT_WRITE)
    raw=(ctypes.c_ubyte*(3*SIZE)).from_buffer(area)
    base=ctypes.addressof(raw)
    ctypes.memset(base+SIZE, 0x44, SIZE)
    for side in (base, base+2*SIZE):
        assert libc.mprotect(side,SIZE,0)==0
    try:
        receipt=ctypes.create_string_buffer(16)  # exactly 16 bytes; no trailing C-string NUL
        for index,old,op,new in ((0,1,1,2),(4095,2,2,1),(4095,1,3,0)):
            ctypes.memset(base+SIZE+index,old,1)
            request = (index.to_bytes(2,"little")+bytes([op,old])+bytes(12))
            req=ctypes.create_string_buffer(request)
            result=entry(ctypes.addressof(req),16,ctypes.addressof(receipt),16,base+SIZE,SIZE)
            assert result==0 and receipt.raw == bytes(8)+bytes([new])+bytes(7)
            assert ctypes.string_at(base+SIZE+index,1)==bytes([new])
    finally:
        for side in (base,base+2*SIZE):
            assert libc.mprotect(side,SIZE,mmap.PROT_READ|mmap.PROT_WRITE)==0
        del raw
        area.close()
    return "PASS"

def main():
    arg=argparse.ArgumentParser()
    arg.add_argument("library",type=Path)
    arg.add_argument("--expect-unsafe",action="store_true")
    opts=arg.parse_args()
    dll=ctypes.CDLL(str(opts.library.resolve()))
    entry=dll.f0
    entry.argtypes=[ctypes.c_void_p,ctypes.c_uint64]*3
    entry.restype=ctypes.c_uint32
    rng=random.Random(20261120)
    total=bad=0
    for slot in (0,1,255,256,4094,4095,4096,65535):
        for old in (0,1,2,4,254,255):
            for action in (0,1,2,3,4):
                table=bytearray([0x5b]*SIZE)
                if slot<SIZE: table[slot]=old
                request=slot.to_bytes(2,"little")+bytes((action,old))+bytes(12)
                total+=1
                bad+=not invoke(entry,request,bytes(table))
    for _ in range(240):
        slot=rng.randrange(0,65536)
        old=rng.randrange(256)
        action=rng.randrange(5)
        table=bytearray(rng.randbytes(SIZE))
        if slot<SIZE and rng.randrange(3):
            table[slot]=old
        request=slot.to_bytes(2,"little")+bytes((action,old))+bytes(12)
        if rng.randrange(8)==0:
            request=request[:rng.randrange(0,16)]
        elif rng.randrange(8)==0:
            request=request[:rng.randrange(4,16)]+b"\x01"+request[rng.randrange(4,16)+1:]
        receipt_len=16 if rng.randrange(5) else rng.choice((0,1,15,17))
        if rng.randrange(7)==0:
            table=table[:rng.choice((0,1,4095))]
        total+=1
        bad+=not invoke(entry,request,bytes(table),receipt_len)
    if opts.expect_unsafe:
        assert bad >= 100,(bad,total)
        print(json.dumps({"native_cases":total,"dishonest_detected":bad,"negative_control":"PASS"}))
    else:
        assert bad==0,(bad,total)
        assert guarded(entry)=="PASS"
        print(json.dumps({"native_cases":total,"oracle_mismatches":bad,"guard_pages":"PASS","status":"PASS"}))

if __name__=="__main__":
    main()
