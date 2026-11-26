#!/usr/bin/env python3
"""Exercise real HIA CAS on a caller-owned packed generation/ready word."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import threading

COMPILER_SHA = "970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4"
COMPILER_SOURCE_SHA = "42f8cccca8b084f42b40a30c3db19df1ffca069295d04666c5290f752e4a9715"
U32 = (1 << 32) - 1
U64 = (1 << 64) - 1

def digest(data):
    return hashlib.sha256(data).hexdigest()

def oracle(live, old, n, task, desired):
    if not 1 <= n <= 32 or task >= n or desired > 1:
        return 6, live
    gen, mask = old >> 32, old & U32
    if mask >> n or gen == U32:
        return 6, live
    if live != old:
        return 9, live
    if bool(mask & (1 << task)) == bool(desired):
        return 7, live
    newmask = (mask | (1 << task)) if desired else (mask & ~(1 << task))
    return 0, ((gen + 1) << 32) | newmask

def worker(library):
    native = ctypes.CDLL(str(library)).f0
    native.argtypes = [ctypes.c_uint64] * 5
    native.restype = ctypes.c_uint64
    storage = (ctypes.c_uint64 * 3)(0x13579bdf, 0, 0x2468ace0)
    addr = ctypes.addressof(storage) + 8
    count = 0
    def check(live, old, n, task, desired):
        nonlocal count
        storage[1] = live
        rc, value = oracle(live, old, n, task, desired)
        assert (native(addr, old, n, task, desired), storage[1]) == (rc, value), (live,old,n,task,desired,rc,value,storage[1])
        assert storage[0] == 0x13579bdf and storage[2] == 0x2468ace0
        count += 1

    # First check normal set/clear, stale full generation and overflow.
    check(0,0,32,31,1)
    check((1<<32)|(1<<31),(1<<32)|(1<<31),32,31,0)
    check(2<<32,0,32,31,1)
    check(U32<<32,U32<<32,32,0,1)
    # A no-op is a statement about the live state, not an old snapshot.
    check(1,0,32,0,0)
    check((1<<32)|1,0,32,0,0)
    check(1<<32,1,32,0,1)
    check((1<<32)|1,1,32,0,1)
    check(0,0,32,0,0)
    check(1,1,32,0,1)
    for n in range(1,9):
        for mask in range(1<<n):
            old = (17<<32)|mask
            for task in range(n):
                for desired in (0,1):
                    check(old,old,n,task,desired)
                    check(old+(1<<32),old,n,task,desired)
    rng = random.Random(20261125)
    for n in range(1,33):
        for _ in range(128):
            old = (rng.randrange(U32)<<32)|rng.getrandbits(n)
            task, desired = rng.randrange(n), rng.randrange(2)
            check(old,old,n,task,desired)
            check(old ^ (1<<32),old,n,task,desired)
        for task in range(n):
            check(0,0,n,task,1)
            check(1<<task,1<<task,n,task,0)
        if n < 32:
            check(1<<n,1<<n,n,0,1)
        check(0,0,n,n,1)
        check(0,0,n,0,2)
    for n in (0,33,U64):
        check(0,0,n,0,1)
    storage[1] = 0
    for bad in (0,addr+1,1<<47,U64):
        assert native(bad,0,32,0,1)==6 and storage[1]==0
        count += 1

    # Eight simultaneous writers start with the same generation and distinct
    # bits. Exactly one may publish, and the winner's bit must be the only bit.
    race_calls = 0
    for round_id in range(32):
        old = round_id<<32
        storage[1] = old
        barrier = threading.Barrier(8)
        results = [None]*8
        def attempt(i):
            barrier.wait(timeout=10)
            results[i] = native(addr,old,32,i,1)
        threads = [threading.Thread(target=attempt,args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=15)
        assert not any(t.is_alive() for t in threads)
        assert results.count(0)==1 and results.count(9)==7, results
        assert storage[1] == ((round_id+1)<<32)|(1<<results.index(0))
        assert storage[0] == 0x13579bdf and storage[2] == 0x2468ace0
        race_calls += 8
    # Repeated concurrent writers toggle disjoint bits with compare-and-retry;
    # every accepted update contributes exactly one generation increment.
    storage[1] = 0
    barrier = threading.Barrier(4)
    results = [None]*4
    def toggle(i):
        barrier.wait(timeout=10)
        calls = 0
        for k in range(1000):
            for _ in range(10000):
                old = storage[1]  # aligned x86-64 read in the test observer
                rc = native(addr,old,32,i,1-(k&1))
                calls += 1
                if rc == 0: break
                assert rc == 9, (i,k,rc)
            else: raise AssertionError("retry bound")
        results[i] = calls
    threads = [threading.Thread(target=toggle,args=(i,)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert all(isinstance(v,int) for v in results), results
    assert storage[1] == (4000<<32)
    assert storage[0] == 0x13579bdf and storage[2] == 0x2468ace0
    print(json.dumps(dict(sequential_calls=count,contended_one_winner_calls=race_calls,concurrent_toggle_calls=sum(results),successful_concurrent_toggles=4000,status="PASS")))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--compiler-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    compiler=(args.compiler_dir/"compiler-rebuilt-2").resolve()
    assert digest(compiler.read_bytes()) == COMPILER_SHA
    assert digest((args.compiler_dir/"candidate.hepta").read_bytes()) == COMPILER_SOURCE_SHA
    source=(Path(__file__).resolve().parents[1]/"src/x86_native_versioned_ready_state.hepta").read_bytes()
    def build(name,subject):
        obj=out/(name+".o")
        binary=subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        assert binary==subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        obj.write_bytes(binary)
        assert not subprocess.check_output(["nm","-u",str(obj)]).strip()
        lib=out/(name+".so")
        subprocess.run(["gcc","-shared","-Wl,-z,noexecstack","-o",str(lib),str(obj)],check=True)
        return obj,lib
    def run(lib):
        return subprocess.run([sys.executable,str(Path(__file__).resolve()),"--worker",str(lib)],capture_output=True,text=True,timeout=120)
    obj,lib=build("state",source)
    result=run(lib)
    (out/"state.stdout").write_text(result.stdout)
    (out/"state.stderr").write_text(result.stderr)
    assert result.returncode==0,result.stderr
    controls={}
    for name,old,new in (
        ("no-generation-advance",b'increment:u64 = const() {"value":1}',b'increment:u64 = const() {"value":0}'),
        ("no-clear",b'toggled:u64 = bit.xor(bitmap,marker)',b'toggled:u64 = bit.or(bitmap,marker)'),
        ("ignore-stale",b'matched:bool = compare.eq(observed,previous)',b'matched:bool = compare.eq(previous,previous)'),
        ("ignore-stale-duplicate",b'dupmatched:bool = compare.eq(duplive,dupold)',b'dupmatched:bool = compare.eq(dupold,dupold)'),
    ):
        assert source.count(old)==1
        mutant_obj,mutant=build(name,source.replace(old,new))
        assert mutant_obj.read_bytes()!=obj.read_bytes()
        r=run(mutant)
        (out/(name+".stderr")).write_text(r.stderr)
        assert r.returncode==1 and "AssertionError" in r.stderr,(name,r.returncode,r.stderr)
        controls[name]="DETECTED"
    report=dict(compiler_sha256=COMPILER_SHA,compiler_source_sha256=COMPILER_SOURCE_SHA,source_sha256=digest(source),object_sha256=digest(obj.read_bytes()),execution=json.loads(result.stdout),negative_controls=controls,packed_generation_bits=32,packed_ready_bits=32,live_duplicate_validation=True,live_irq_dispatch_proved=False,resource_authority_proved=False,full_linux_acceptance="HOLD")
    (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))

if __name__=="__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--worker":
        worker(Path(sys.argv[2]))
    else:
        main()
