#!/usr/bin/env python3
"""Native scalar round-robin selector; not a scheduler or Linux acceptance."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

COMPILER_SHA = "970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4"
U64 = (1 << 64) - 1

def digest(data):
    return hashlib.sha256(data).hexdigest()

def oracle(mask, n, cur):
    if not 1 <= n <= 64 or not 0 <= cur < n or mask >> n:
        return 65
    candidates = [i for i in range(n) if mask & (1 << i)]
    return min(candidates, key=lambda i: ((i-cur-1) % n)) if candidates else 64

def worker(library):
    f = ctypes.CDLL(str(library)).f0
    f.argtypes = [ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint64
    rng = random.Random(20261125)
    count = 0
    def check(mask, n, cur):
        nonlocal count
        expected = oracle(mask,n,cur)
        actual = f(mask,n,cur)
        assert actual == expected, (mask,n,cur,expected,actual)
        count += 1
    for n in range(1,13):
        for mask in range(1 << n):
            for cur in range(n):
                check(mask,n,cur)
    for n in range(1,65):
        for cur in range(n):
            for mask in (0, (1 << n)-1, 1<<cur, 1<<((cur+1)%n), 1<<(n-1)):
                check(mask,n,cur)
            if n < 64:
                check(1<<n,n,cur)
        for mask in (0, 1, U64):
            check(mask,n,n)
            check(mask,n,U64)
        for _ in range(256):
            mask = rng.getrandbits(n)
            cur = rng.randrange(n)
            check(mask,n,cur)
            # Every ready task must appear once before any repetition.
            if mask:
                visited = set()
                for _ in range(mask.bit_count()):
                    next_id = f(mask,n,cur)
                    assert next_id == oracle(mask,n,cur) and next_id not in visited
                    count += 1
                    visited.add(next_id)
                    cur = next_id
                assert visited == {i for i in range(n) if mask & (1<<i)}
    for n in (0,65,U64):
        for mask in (0,1,U64):
            for cur in (0,63,U64):
                check(mask,n,cur)
    print(json.dumps({"native_calls":count,"status":"PASS"}))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--compiler-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    compiler=(args.compiler_dir/"compiler-rebuilt-2").resolve()
    assert digest(compiler.read_bytes()) == COMPILER_SHA
    source=(Path(__file__).resolve().parents[1]/"src/x86_native_ready_bitmap.hepta").read_bytes()
    def build(name, subject):
        obj=out/(name+".o")
        binary=subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        assert binary==subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        obj.write_bytes(binary)
        lib=out/(name+".so")
        subprocess.run(["gcc","-shared","-Wl,-z,noexecstack","-o",str(lib),str(obj)],check=True)
        return obj,lib
    def run(lib):
        return subprocess.run([sys.executable,str(Path(__file__).resolve()),"--worker",str(lib)],capture_output=True,text=True,timeout=120)
    obj,lib=build("ready",source)
    result=run(lib)
    (out/"ready.stdout").write_text(result.stdout)
    (out/"ready.stderr").write_text(result.stderr)
    assert result.returncode==0,result.stderr
    mutations=[
        ("wrong-idle",b'{"value":64}\n  ret(idlecode)',b'{"value":63}\n  ret(idlecode)'),
        ("ignore-ready-bit",b'hit:bool = compare.ne(active,pzero)',b'hit:bool = compare.eq(active,pzero)'),
        ("ignore-upper-bits",b'clean:bool = compare.eq(upper,bz)',b'clean:bool = compare.ne(upper,bz)'),
    ]
    controls={}
    for name,old,new in mutations:
        assert source.count(old)==1
        mutant_obj,mutant=build(name,source.replace(old,new))
        assert mutant_obj.read_bytes()!=obj.read_bytes()
        r=run(mutant)
        (out/(name+".stderr")).write_text(r.stderr)
        assert r.returncode==1 and "AssertionError" in r.stderr, (name,r.returncode,r.stderr)
        controls[name]="DETECTED"
    report={"compiler_sha256":COMPILER_SHA,"source_sha256":digest(source),"object_sha256":digest(obj.read_bytes()),"selector":json.loads(result.stdout),"negative_controls":controls,"actual_multitask_preemption_proved":False,"full_linux_acceptance":"HOLD"}
    (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))

if __name__=="__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--worker":
        worker(Path(sys.argv[2]))
    else:
        main()

