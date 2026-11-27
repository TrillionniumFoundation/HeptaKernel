#!/usr/bin/env python3
"""Native atomic preemption exchange: current remains runnable; not a context switch."""
import argparse, ctypes, hashlib, json, random, subprocess, sys, threading
from pathlib import Path
COMPILER_SHA = "970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4"
COMPILER_SOURCE_SHA = "42f8cccca8b084f42b40a30c3db19df1ffca069295d04666c5290f752e4a9715"
U32=(1<<32)-1
U64=(1<<64)-1
def digest(b): return hashlib.sha256(b).hexdigest()
def oracle(live, expected, n, current):
    generation, ready = divmod(expected, 1<<32)
    if not 1<=n<=32 or current>=n or generation==U32 or ready>>n or ready & (1<<current):
        return 65, live
    if live!=expected: return 66, live
    order=list(range(current+1,n))+list(range(current))
    for task in order:
        if ready & (1<<task):
            return task, ((generation+1)<<32)|(ready & ~(1<<task))|(1<<current)
    return current, live
def load(path, args):
    native=ctypes.CDLL(str(path)).f0
    native.argtypes=[ctypes.c_uint64]*args
    native.restype=ctypes.c_uint64
    return native
def worker(lib, publisher):
    native=load(lib,4)
    publish=load(publisher,5)
    storage=(ctypes.c_uint64*3)(0x13579bdf,0,0x2468ace0)
    addr=ctypes.addressof(storage)+8
    calls=0
    def guards():
        assert storage[0]==0x13579bdf and storage[2]==0x2468ace0
    def check(live,old,n,cur):
        nonlocal calls
        storage[1]=live
        want=oracle(live,old,n,cur)
        got=(native(addr,old,n,cur),storage[1])
        assert got==want,(live,old,n,cur,got,want)
        guards()
        calls+=1
    for n in range(1,11):
        for mask in range(1<<n):
            old=(17<<32)|mask
            for cur in range(n):
                check(old,old,n,cur)
                check(old+(1<<32),old,n,cur)
    rng=random.Random(20261125)
    for n in range(1,33):
        for _ in range(128):
            cur=rng.randrange(n)
            mask=rng.getrandbits(n)&~(1<<cur)
            old=(rng.randrange(U32)<<32)|mask
            check(old,old,n,cur)
            check(old^(1<<32),old,n,cur)
            check(old|(1<<cur),old|(1<<cur),n,cur)
        check(0,0,n,0)
        check(1<<32,0,n,0)
        check(0,0,n,n)
        check(U32<<32,U32<<32,n,0)
        if n<32: check(1<<n,1<<n,n,0)
    for n in (0,33,U64): check(0,0,n,0)
    for bad in (0,addr+1,1<<47,U64):
        storage[1]=0
        assert native(bad,0,32,0)==65 and storage[1]==0
        calls+=1
    rotations=0
    for n in range(2,33):
        current=n-1
        storage[1]=((1<<n)-1)&~(1<<current)
        for step in range(n*4):
            old=storage[1]
            selected=native(addr,old,n,current)
            assert selected==(current+1)%n
            assert storage[1]==((step+1)<<32)|(((1<<n)-1)&~(1<<selected))
            current=selected
            rotations+=1
            guards()
    races=0
    for i in range(128):
        old=(i<<32)|2
        storage[1]=old
        barrier=threading.Barrier(2)
        results=[None,None]
        def preempt():
            barrier.wait(timeout=10)
            results[0]=native(addr,old,3,0)
        def wake():
            barrier.wait(timeout=10)
            results[1]=publish(addr,old,3,2,1)
        a=threading.Thread(target=preempt); b=threading.Thread(target=wake)
        a.start(); b.start(); a.join(10); b.join(10)
        assert not a.is_alive() and not b.is_alive()
        if results==[1,9]:
            assert storage[1]==((i+1)<<32)|1
        elif results==[66,0]:
            assert storage[1]==((i+1)<<32)|6
        else: raise AssertionError(results)
        guards()
        races+=1
    print(json.dumps(dict(sequential_calls=calls,rotation_steps=rotations,publisher_races=races,status="PASS")))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--compiler-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    out=a.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    compiler=(a.compiler_dir/"compiler-rebuilt-2").resolve()
    assert digest(compiler.read_bytes())==COMPILER_SHA
    assert digest((a.compiler_dir/"candidate.hepta").read_bytes())==COMPILER_SOURCE_SHA
    root=Path(__file__).resolve().parents[1]
    source=(root/"src/x86_native_ready_exchange.hepta").read_bytes()
    publisher=(root/"src/x86_native_versioned_ready_state.hepta").read_bytes()
    def build(name,subject):
        obj=out/(name+".o")
        binary=subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        assert binary==subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        obj.write_bytes(binary)
        assert not subprocess.check_output(["nm","-u",str(obj)]).strip()
        lib=out/(name+".so")
        subprocess.run(["gcc","-shared","-Wl,-z,noexecstack","-o",str(lib),str(obj)],check=True)
        return obj,lib
    po,pl=build("publisher",publisher)
    obj,lib=build("exchange",source)
    def run(lib): return subprocess.run([sys.executable,str(Path(__file__).resolve()),"--worker",str(lib),str(pl)],capture_output=True,text=True,timeout=120)
    r=run(lib)
    (out/"exchange.stdout").write_text(r.stdout)
    (out/"exchange.stderr").write_text(r.stderr)
    assert r.returncode==0,r.stderr
    controls={}
    for name,old,new in (
        ("no-requeue",b'nextbits:u64 = bit.or(removed,outgoingbit)',b'nextbits:u64 = bit.or(removed,removed)'),
        ("no-remove",b'removed:u64 = bit.xor(oldbits,bit)',b'removed:u64 = bit.or(oldbits,bit)'),
        ("ignore-running-ready",b'runningabsent:bool = compare.eq(curbit,curzero)',b'runningabsent:bool = compare.eq(curzero,curzero)'),
        ("ignore-stale-exchange",b'matched:bool = compare.eq(seen,oldword)',b'matched:bool = compare.eq(oldword,oldword)'),
        ("ignore-stale-stay",b'same:bool = compare.eq(live,idold)',b'same:bool = compare.eq(idold,idold)'),
    ):
        assert source.count(old)==1
        mo,ml=build(name,source.replace(old,new))
        assert mo.read_bytes()!=obj.read_bytes()
        m=run(ml)
        (out/(name+".stderr")).write_text(m.stderr)
        assert m.returncode==1 and "AssertionError" in m.stderr,(name,m.returncode,m.stderr)
        controls[name]="DETECTED"
    report=dict(compiler_sha256=COMPILER_SHA,compiler_source_sha256=COMPILER_SOURCE_SHA,source_sha256=digest(source),object_sha256=digest(obj.read_bytes()),publisher_source_sha256=digest(publisher),publisher_object_sha256=digest(po.read_bytes()),execution=json.loads(r.stdout),negative_controls=controls,atomic_ready_exchange=True,live_irq_dispatch_proved=False,resource_authority_proved=False,full_linux_acceptance="HOLD")
    (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
if __name__=="__main__":
    if len(sys.argv)==4 and sys.argv[1]=="--worker": worker(Path(sys.argv[2]),Path(sys.argv[3]))
    else: main()
