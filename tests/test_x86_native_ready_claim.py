#!/usr/bin/env python3
"""Real native packed-ready claim; independent oracle, not IRQ/authority acceptance."""
import argparse, ctypes, hashlib, json, random, subprocess, sys, threading
from pathlib import Path
COMPILER_SHA = "970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4"
COMPILER_SOURCE_SHA = "42f8cccca8b084f42b40a30c3db19df1ffca069295d04666c5290f752e4a9715"
U32 = (1<<32)-1
U64 = (1<<64)-1
def digest(data): return hashlib.sha256(data).hexdigest()
def oracle(live, expected, n, cursor):
    gen, mask = expected>>32, expected & U32
    if not 1<=n<=32 or cursor>=n or gen==U32 or mask>>n:
        return 65, live
    if live!=expected: return 66, live
    for distance in range(1,n+1):
        task=(cursor+distance)%n
        if mask & (1<<task):
            return task, ((gen+1)<<32)|(mask & ~(1<<task))
    return 64, live
def worker(lib):
    native=ctypes.CDLL(str(lib)).f0
    native.argtypes=[ctypes.c_uint64]*4
    native.restype=ctypes.c_uint64
    storage=(ctypes.c_uint64*3)(0x13579bdf,0,0x2468ace0)
    addr=ctypes.addressof(storage)+8
    calls=0
    def check(live,old,n,cur):
        nonlocal calls
        storage[1]=live
        expected=oracle(live,old,n,cur)
        got=(native(addr,old,n,cur),storage[1])
        assert got==expected,(live,old,n,cur,got,expected)
        assert storage[0]==0x13579bdf and storage[2]==0x2468ace0
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
            old=(rng.randrange(U32)<<32)|rng.getrandbits(n)
            cur=rng.randrange(n)
            check(old,old,n,cur)
            check(old^1<<32,old,n,cur)
        check(0,0,n,0)
        check(1<<32,0,n,0)
        check(0,0,n,n)
        check(U32<<32,U32<<32,n,0)
        if n<32: check(1<<n,1<<n,n,0)
        check(1<<(n-1),1<<(n-1),n,n-1)
    for n in (0,33,U64): check(0,0,n,0)
    for bad in (0,addr+1,1<<47,U64):
        storage[1]=0
        assert native(bad,0,32,0)==65 and storage[1]==0
        calls+=1
    total=0
    for round_id in range(32):
        storage[1]=U32
        barrier=threading.Barrier(8)
        results=[None]*8
        def drain(i):
            barrier.wait(timeout=10)
            selected=[]
            for _ in range(10000):
                snapshot=storage[1]
                rc=native(addr,snapshot,32,i)
                if rc==64: break
                if rc==66: continue
                assert 0<=rc<32,rc
                selected.append(rc)
            else: raise AssertionError("retry bound")
            results[i]=selected
        threads=[threading.Thread(target=drain,args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=15)
        assert not any(t.is_alive() for t in threads)
        assert all(isinstance(x,list) for x in results),results
        claimed=[v for x in results for v in x]
        assert sorted(claimed)==list(range(32)),claimed
        assert storage[1]==32<<32
        assert storage[0]==0x13579bdf and storage[2]==0x2468ace0
        total+=len(claimed)
    print(json.dumps(dict(sequential_calls=calls,concurrent_unique_claims=total,drain_rounds=32,status="PASS")))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--compiler-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    compiler=(a.compiler_dir/"compiler-rebuilt-2").resolve()
    assert digest(compiler.read_bytes())==COMPILER_SHA
    assert digest((a.compiler_dir/"candidate.hepta").read_bytes())==COMPILER_SOURCE_SHA
    source=(Path(__file__).resolve().parents[1]/"src/x86_native_ready_claim.hepta").read_bytes()
    def build(name,subject):
        obj=out/(name+".o")
        binary=subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        assert binary==subprocess.run([str(compiler)],input=subject,env={"PATH":""},check=True,capture_output=True,timeout=60).stdout
        obj.write_bytes(binary)
        assert not subprocess.check_output(["nm","-u",str(obj)]).strip()
        lib=out/(name+".so")
        subprocess.run(["gcc","-shared","-Wl,-z,noexecstack","-o",str(lib),str(obj)],check=True)
        return obj,lib
    def run(lib): return subprocess.run([sys.executable,str(Path(__file__).resolve()),"--worker",str(lib)],capture_output=True,text=True,timeout=120)
    obj,lib=build("claim",source)
    result=run(lib)
    (out/"claim.stdout").write_text(result.stdout)
    (out/"claim.stderr").write_text(result.stderr)
    assert result.returncode==0,result.stderr
    controls={}
    for name,old,new in (
        ("no-clear",b'nextbits:u64 = bit.xor(oldbits,bit)',b'nextbits:u64 = bit.or(oldbits,bit)'),
        ("no-generation-advance",b'nextgen:u64 = int.add.wrap(oldgen,one)',b'nextgen:u64 = int.sub.wrap(oldgen,one)'),
        ("ignore-stale-claim",b'matched:bool = compare.eq(seen,oldword)',b'matched:bool = compare.eq(oldword,oldword)'),
        ("ignore-stale-idle",b'same:bool = compare.eq(live,idold)',b'same:bool = compare.eq(idold,idold)'),
    ):
        assert source.count(old)==1
        mo,ml=build(name,source.replace(old,new))
        assert mo.read_bytes()!=obj.read_bytes()
        r=run(ml)
        (out/(name+".stderr")).write_text(r.stderr)
        assert r.returncode==1 and "AssertionError" in r.stderr,(name,r.returncode,r.stderr)
        controls[name]="DETECTED"
    report=dict(compiler_sha256=COMPILER_SHA,compiler_source_sha256=COMPILER_SOURCE_SHA,source_sha256=digest(source),object_sha256=digest(obj.read_bytes()),execution=json.loads(result.stdout),negative_controls=controls,live_irq_dispatch_proved=False,resource_authority_proved=False,full_linux_acceptance="HOLD")
    (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
if __name__=="__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--worker": worker(Path(sys.argv[2]))
    else: main()
