#!/usr/bin/env python3
"""Independent bounded x86-64 ELF initial stack oracle and native negative control."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import tempfile

TOP = 1 << 47
SEED = 2026112204

def oracle(req, page, receipt):
    if len(req) != 40:
        return 1, page, receipt
    if len(page) != 4096 or len(receipt) != 16:
        return 2, page, receipt
    base, entry, phdr, phent, phnum = struct.unpack("<5Q", req)
    if not (0 < base <= TOP-4096 and base % 4096 == 0
            and 4096 <= entry < TOP and 4096 <= phdr <= TOP-8192
            and phent == 56 and 1 <= phnum <= 128):
        return 3, page, receipt
    words = (0, 0, 0, 3, phdr, 4, 56, 5, phnum, 6, 4096, 9, entry, 0, 0, 0)
    updated = bytearray(page)
    updated[3968:] = struct.pack("<16Q", *words)
    return 0, bytes(updated), struct.pack("<2Q", base+3968, 128)

def load(path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    return f

def invoke(f, req, page, receipt):
    a = ctypes.create_string_buffer(b"\x91"*32 + req + b"\x91"*32)
    b = ctypes.create_string_buffer(b"\xa3"*32 + page + b"\xa3"*32)
    c = ctypes.create_string_buffer(b"\xb5"*32 + receipt + b"\xb5"*32)
    old = bytes(a)
    rc = f(ctypes.addressof(a)+32, len(req),
           ctypes.addressof(b)+32, len(page),
           ctypes.addressof(c)+32, len(receipt))
    assert bytes(a) == old, "source mutated"
    assert bytes(b)[:32] == bytes(b)[32+len(page):32+len(page)+32] == b"\xa3"*32
    assert bytes(c)[:32] == bytes(c)[32+len(receipt):32+len(receipt)+32] == b"\xb5"*32
    return rc, bytes(b)[32:32+len(page)], bytes(c)[32:32+len(receipt)]

def text_hash(obj, lib):
    with tempfile.TemporaryDirectory() as d:
        out = []
        for i, path in enumerate((obj, lib)):
            target = Path(d)/str(i)
            subprocess.run(["objcopy","--only-section=.text","-O","binary",
                            str(path.resolve()),str(target)],check=True,timeout=20)
            raw = target.read_bytes()
            assert raw, "missing genuine native .text"
            out.append(hashlib.sha256(raw).hexdigest())
        assert out[0] == out[1], "object .text differs from shared .text"
        return out[0]

def run(library, obj, dishonest):
    fun = load(library)
    rng = random.Random(SEED)
    good = (0x7ffff000, 0x401000, 0x400040, 56, 3)
    cases = [(struct.pack("<5Q",*good),4096,16)]
    for _ in range(4000):
        case = (rng.randrange(1,1<<35)*4096,
                rng.randrange(4096,TOP),
                rng.randrange(4096,TOP-8192+1),
                56, rng.randrange(1,129))
        cases.append((struct.pack("<5Q",*case),4096,16))
    for i in range(4500):
        case = list(good)
        kind = i % 9
        if kind == 0: case[0] = rng.choice((0,1,TOP,TOP-2048))
        if kind == 1: case[1] = rng.choice((0,1,TOP,(1<<64)-1))
        if kind == 2: case[2] = rng.choice((0,1,TOP-1,TOP))
        if kind == 3: case[3] = rng.choice((0,32,64,(1<<64)-1))
        if kind == 4: case[4] = rng.choice((0,129,(1<<64)-1))
        req = struct.pack("<5Q",*case)
        if kind == 5: req = req[:rng.randrange(40)]
        if kind == 6: req += b"\0"*rng.randrange(1,32)
        size = 4096 if kind != 7 else rng.choice((0,1,4095,4097))
        msize = 16 if kind != 8 else rng.choice((0,1,8,17))
        cases.append((req,size,msize))
    counts = {str(i):0 for i in range(4)}
    mismatches = 0
    for req, size, msize in cases:
        page = rng.randbytes(size)
        receipt = rng.randbytes(msize)
        expected = oracle(req,page,receipt)
        actual = invoke(fun,req,page,receipt)
        mismatches += (actual != expected)
        counts[str(expected[0])] += 1
        if not dishonest:
            assert actual == expected, (req.hex(),size,msize,actual[0],expected[0])
    if dishonest:
        assert mismatches >= 50, ("always-success HIA negative control escaped",mismatches)
        print("HIA_ELF64_STACK_DISHONEST_CONTROL: DETECTED", mismatches)
        return
    assert counts["0"] >= 4000 and all(counts.values()), counts
    report = {
        "schema":"heptakernel.hia-elf64-start-stack.v1",
        "seed":SEED,"cases":len(cases),"by_status":counts,
        "status":"PASS","full_linux":"HOLD","stack_mapped":False,
        "real_execve":False,"dishonest_control_required":True,
        "source_sha256":hashlib.sha256(Path("src/elf64_start_stack.hepta").read_bytes()).hexdigest()
    }
    if obj:
        report["text_sha256"] = text_hash(obj,library)
    Path("build/elf64-start-stack-report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("HIA_ELF64_STACK_NATIVE_ORACLE: PASS",json.dumps(report,sort_keys=True))

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("library",type=Path)
    p.add_argument("--object",type=Path)
    p.add_argument("--dishonest",action="store_true")
    a=p.parse_args()
    run(a.library,a.object,a.dishonest)
