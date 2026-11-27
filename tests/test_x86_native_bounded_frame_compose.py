#!/usr/bin/env python3
"""Independent hardware observer for three fixed BSP tasks, not general SMP."""
import argparse, ctypes, hashlib, json, subprocess, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
COMPILER = "970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4"
COMPILER_SOURCE = "42f8cccca8b084f42b40a30c3db19df1ffca069295d04666c5290f752e4a9715"
def sha(b): return hashlib.sha256(b).hexdigest()
def run(args, **kw):
    return subprocess.run([str(a) for a in args],check=True,capture_output=True,timeout=60,**kw).stdout
def text(obj,dest):
    run(["objcopy","-O","binary","--only-section=.text",obj,dest])
    return dest.read_bytes()
def sym(obj,name):
    rows=[r.split() for r in run(["nm","-n",obj]).decode().splitlines() if r.split()[-1:]==[name]]
    assert len(rows)==1, (obj,name,rows)
    return int(rows[0][0],16)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--compiler-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    c=(a.compiler_dir/"compiler-rebuilt-2").resolve()
    assert sha(c.read_bytes())==COMPILER
    assert sha((a.compiler_dir/"candidate.hepta").read_bytes())==COMPILER_SOURCE
    qualification=json.loads((a.compiler_dir/"report.json").read_bytes())
    assert qualification["status"]=="PASS" and qualification["native_generations"]==3 and qualification["empty_path_rebuilds"]==2
    files={
        "schedule":("x86_two_task_preemption.hepta",{}, "e3ff686aa2f6ae3f7698e1d61fe1fc42ef8e707cab2001635e76dc5d96f86381"),
        "restore":("x86_native_kernel_frame.hepta",{"f0":"hia_restore_frame"}, "dd2f89a4864066746d4229fa22745380e29b77ca65e323ddcb53115a3b46e419"),
        "irq":("x86_native_irq_entry.hepta",{"f0":"hia_irq_entry"}, "f42b5bc59894dd99ec6bbb42f01e9ea2da4843931103e8438717cb9cb415331a"),
        "handoff":("x86_native_owner_dispatch.hepta",{f"f{i}":n for i,n in enumerate(["hia_publish_frame","hia_consume_frame","hia_switch_frames","hia_publish_owner","hia_select_parked_slot"])},"a72af0c4b7884b81ed2f9406dd811e2d6e3239317b2fa6c1ffed8a04ff3b77e1"),
        "exchange":("x86_native_ready_exchange.hepta",{"f0":"hia_ready_exchange","f1":"hia_ready_select"},"90c793a1e883c04157366e0ef2f6bc210afea7b32d8397c5f811b9b664a1c2a1"),
        "publisher":("x86_native_versioned_ready_state.hepta",{"f0":"hia_publish_ready"},"fc4377904d2fc5bb33e5a49033c01336c10555932b6939c2b3930cde216a5487"),
        "owner":("x86_native_bounded_owner.hepta",{"f0":"hia_publish_bounded_owner"},"863f562b05958d8e224cb1af8d075e60091df9ba1ec9c515f616fd91d8788f9f"),
        "dispatch":("x86_native_bounded_slot_dispatch.hepta",{"f0":"hia_resolve_slot"},"c67bd59279dc31b097ffabaa330a0a58ea18f4416493b156d4fa6d1e0d4e9cd7"),
        "compensation":("x86_native_ready_compensation.hepta",{"f0":"hia_compensate_ready"},"f6ab489646e65f9195d722dd6ed097b4f612de1298a88a49ad6b882edfe27aca"),
        "guard":("x86_native_frame_rollback_guard.hepta",{"f0":"hia_guard_frame_rollback"},"af14993095253dcf81ac06e89ceb7692bd89ae311c5a7d97b6e06af89be3ff8f"),
        "block":("x86_native_running_block.hepta",{"f0":"hia_block_running"},"be1fd771bc74c730e29c6870efe121edbef534d61f14b6b5c7d2f057b34346f2"),
        "idle":("x86_native_idle_select.hepta",{"f0":"hia_idle_select"},"17ffdc9a5a27d7aaa31e6a6affc6dd7e61d6f89c551e3830d81f5fb863b990fd"),
        "idle_comp":("x86_native_idle_compensation.hepta",{"f0":"hia_compensate_idle"},"c4975cb6f2b4af844e25c01d9d8b35e7d23fd7872a52bb86f98812ed2a842509"),
    }
    files["policy"]=("x86_native_dispatch_policy.hepta",{"f0":"hia_dispatch_policy"},"7fd1abb8efca9fe2a0d83a4ae3c62c2958ee12bdf982f5bf3124db082558028b")
    files["reserved"]=("x86_native_reserved_policy.hepta",{"f0":"hia_reserved_policy"},'e673b2e97c1f5f937632a2ab7078e340b9a7dda10c249aa2fec2dd6eee287005')
    files["reserved_comp"]=("x86_native_reserved_compensation.hepta",{"f0":"hia_reserved_compensation"},"31f3b97d3d07837e095a403261c18f5151e84774652dd8123892551d4baff1d0")
    files["compose"]=("x86_native_bounded_frame_compose.hepta",{"f0":"hia_bounded_frame_compose"},"3f6834d41ee0f45bc5cede14da7e2db34823a2464c65903056ac07014da56b79")
    sources={name:(ROOT/"src"/path).read_bytes() for name,(path,_,_) in files.items()}
    # Confirm every composed native function body derives byte-for-byte
    # from its inherited implementation, except function-symbol renames.
    composed=b"hia-asm.v1 hepta.hia.program.kernel-tlb.v1 selfhost_elf\nexports(f0)\n"
    for key,n in (("exchange",2),("block",4),("idle",6)):
        body=b"\n".join(sources[key].splitlines()[2:])+b"\n"
        composed+=re.sub(rb"\bf([01])\b",lambda m:f"f{n+int(m[1])}".encode(),body)
    assert sources["policy"].startswith(composed)
    assert sources["policy"][len(composed):].startswith(b"fn f0(")
    framebody=sources["handoff"][sources["handoff"].index(b"fn f0("):sources["handoff"].index(b"fn f3(")]
    framebody=re.sub(rb"\bf([012])\b",lambda m:f"f{int(m[1])+2}".encode(),framebody)
    resolver=re.sub(rb"\bf0\b",b"f1",b"\n".join(sources["dispatch"].splitlines()[2:])+b"\n")
    prefix=b"\n".join(sources["handoff"].splitlines()[:1])+b"\nexports(f0)\n"+framebody+resolver
    assert sources["compose"].startswith(prefix) and sources["compose"][len(prefix):].startswith(b"fn f0(")
    record={"status":"FAIL","compiler_sha256":COMPILER,"compiler_source_sha256":COMPILER_SOURCE,"objects":{},"cases":[],"full_linux_acceptance":"HOLD","general_atomic_transaction_proved":False,"resource_authority_proved":False,"general_smp_proved":False}
    def build(name,source,label):
        _,renames,expected=files[name]
        raw=out/(label+".o")
        native=run([c],input=source,env={"PATH":""})
        assert native==run([c],input=source,env={"PATH":""})
        raw.write_bytes(native)
        if label==name and expected: assert sha(native)==expected,(name,sha(native))
        assert not run(["nm","-u",raw]).strip()
        assert b"There are no relocations" in run(["readelf","-Wr",raw])
        original=text(raw,out/(label+".text"))
        linked=out/(label+"-linked.o")
        opts=[f"--redefine-sym={old}={new}" for old,new in renames.items()]
        run(["objcopy",*opts,raw,linked])
        assert text(linked,out/(label+"-linked.text"))==original
        export=renames.get("f0","f0")
        assert sym(raw,"f0")==sym(linked,export)
        return (linked,original,export), {"source_sha256":sha(source),"object_sha256":sha(native),"text_sha256":sha(original)}
    def host_dispatch_oracle():
        # Linux x86-64 MAP_32BIT obtains a real low mapping; the HIA ABI
        # further requires the full table and frame to be below 1 GiB.
        libc=ctypes.CDLL(None,use_errno=True)
        libc.mmap.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_long]
        libc.mmap.restype=ctypes.c_void_p
        libc.munmap.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
        size=4096
        # MAP_FIXED_NOREPLACE never replaces existing mappings.
        addr=None
        for requested in range(0x20000000,0x30000000,0x100000):
            got=libc.mmap(requested,size,3,0x100022,-1,0)
            if got==requested:
                addr=got
                break
            if got not in (None,ctypes.c_void_p(-1).value):
                libc.munmap(got,size)
        assert addr is not None, "no isolated low mapping"
        try:
            libpath=out/"dispatch-host.so"
            run(["cc","-shared","-nostdlib","-o",libpath,objects["dispatch"][0]])
            lib=ctypes.CDLL(str(libpath))
            fn=lib.hia_resolve_slot
            fn.argtypes=[ctypes.c_uint64]*4
            fn.restype=ctypes.c_uint64
            words=(ctypes.c_uint64*34).from_address(addr)
            words[0]=0x123456789
            words[33]=0x987654321
            base=addr+8
            frame=addr+1024
            for i in range(32): words[1+i]=frame+8*i
            original=bytes(words)
            calls=0
            for n in range(1,33):
                for i in range(n):
                    assert fn(base,n,i,frame+8*i)==base+8*i
                    assert fn(base,n,i,frame+8*i+512)==0
                    calls+=2
                assert fn(base,n,n,frame)==0
                calls+=1
            bad=[(base,0,0,frame),(base,33,0,frame),(base,2,2**64-1,frame),
                 (base+1,1,0,frame),(0,1,0,frame),(base,1,0,0),
                 (base,1,0,frame+1),(0x3ffffff8,2,0,frame),
                 (base,1,0,0x3fffff68),(base,32,0,base),
                 (base,32,0,base+32*8-8),(base,1,0,2**64-8)]
            for args in bad:
                assert fn(*args)==0,args
                calls+=1
            assert bytes(words)==original
            return calls
        finally:
            assert libc.munmap(addr,size)==0
    def host_compensation_oracle():
        libpath=out/"compensation-host.so"
        run(["cc","-shared","-nostdlib","-o",libpath,objects["compensation"][0]])
        lib=ctypes.CDLL(str(libpath))
        fn=lib.hia_compensate_ready
        fn.argtypes=[ctypes.c_uint64]*5
        fn.restype=ctypes.c_uint64
        cell=(ctypes.c_uint64*3)(0x12345678,0,0x23456789)
        addr=ctypes.addressof(cell)+8
        calls=0
        for n in range(2,33):
            for dep in range(n):
                for sel in range(n):
                    if dep==sel: continue
                    for gen in (0,17,0xfffffffd):
                        bits=((1<<n)-1) ^ (1<<dep)
                        before=(gen<<32)|bits
                        after=((gen+1)<<32)|((bits^(1<<sel))|(1<<dep))
                        restored=((gen+2)<<32)|bits
                        cell[1]=after
                        assert fn(addr,before,n,dep,sel)==0
                        assert cell[1]==restored
                        assert fn(addr,before,n,dep,sel)==66
                        assert cell[1]==restored
                        # Concurrent publication changed the exact generation.
                        cell[1]=after^(1<<32)
                        old=cell[1]
                        assert fn(addr,before,n,dep,sel)==66
                        assert cell[1]==old
                        calls+=3
        for args in [(addr,2,0,0,1),(addr,2,33,0,1),(addr,2,2,0,0),
                     (addr,2,2,2,1),(addr,2,2,0,2),(addr,3,2,0,1),
                     (addr,0,2,0,1),(addr,6,2,0,1),(addr,(0xfffffffe<<32)|2,2,0,1),
                     (0,2,2,0,1),(addr+1,2,2,0,1)]:
            old=cell[1]
            assert fn(*args)==65,args
            assert cell[1]==old
            calls+=1
        assert cell[0]==0x12345678 and cell[2]==0x23456789
        return calls
    def source_mutant(name,old,new,label):
        src=sources[name]
        assert src.count(old)==1
        mutated,meta=build(name,src.replace(old,new),label)
        assert mutated[1]!=objects[name][1]
        record["objects"][label]=meta
        return mutated
    def machine_mutant(name,label,needle,offset):
        linked,code,export=objects[name]
        assert code[offset:offset+len(needle)]==needle
        changed=code[:offset]+b"\x90"*len(needle)+code[offset+len(needle):]
        raw=out/(label+".text"); raw.write_bytes(changed)
        mutant=out/(label+".o")
        run(["objcopy","--update-section",".text="+str(raw),linked,mutant])
        assert text(mutant,out/(label+"-readback.text"))==changed
        assert sym(mutant,export)==sym(linked,export)
        record["objects"][label]={"object_sha256":sha(mutant.read_bytes()),"text_sha256":sha(changed),"patched_offset":offset,"deleted_hex":needle.hex()}
        return mutant,changed,export
    objects={}
    try:
        for name,src in sources.items():
            objects[name],record["objects"][name]=build(name,src,name)
        libpath=out/"policy-host.so"
        run(["cc","-shared","-nostdlib","-o",libpath,objects["policy"][0]])
        lib=ctypes.CDLL(str(libpath))
        policy=lib.hia_dispatch_policy
        policy.argtypes=[ctypes.c_uint64]*5
        policy.restype=ctypes.c_uint64
        cell=(ctypes.c_uint64*3)(0x12345678,0,0x23456789)
        addr=ctypes.addressof(cell)+8
        count_policy=0
        for n in (1,2,3,4,5,8,32):
            for cur in range(n):
                masks=range(1<<n) if n<=8 else (0,1,2,1<<30,1<<31,0xffffffff,0x55555555,0xaaaaaaaa)
                for mask in masks:
                    for reason in (0,1,2,3,0xffffffffffffffff):
                        for gen in (0,17,0xffffffff):
                            prior=(gen<<32)|mask
                            cell[1]=prior
                            bad=(reason>2 or gen==0xffffffff or mask>>n or mask&(1<<cur) or (reason==2 and (n<2 or mask&(1<<(n-1)))))
                            if bad:
                                selected,new=65,prior
                            else:
                                candidates=[(cur+k)%n for k in range(1,n) if mask&(1<<((cur+k)%n))]
                                if candidates:
                                    selected=candidates[0]
                                    bits=mask^(1<<selected)
                                    if reason==0: bits|=1<<cur
                                    new=((gen+1)<<32)|bits
                                elif reason==0:
                                    selected,new=cur,prior
                                elif reason==1 or cur==n-1:
                                    selected,new=64,prior
                                else:
                                    selected,new=n-1,(gen+1)<<32
                            result=policy(addr,prior,n,cur,reason)
                            assert (result,cell[1])==(selected,new),(n,cur,mask,reason,gen,result,cell[1],selected,new)
                            count_policy+=1
                            if not bad:
                                live=prior^(1<<32)
                                cell[1]=live
                                assert policy(addr,prior,n,cur,reason)==66
                                assert cell[1]==live
                                count_policy+=1
        for args in [(0,0,2,0,0),(addr+1,0,2,0,0),(addr,0,0,0,0),(addr,0,33,0,1),(addr,0,2,2,2)]:
            old=cell[1]
            assert policy(*args)==65 and cell[1]==old,args
            count_policy+=1
        assert cell[0]==0x12345678 and cell[2]==0x23456789
        record["host_policy_calls"]=count_policy
        record["host_dispatch_calls"]=host_dispatch_oracle()
        record["host_compensation_calls"]=host_compensation_oracle()
        # Independent host oracle: never requeue the departing task; no
        # eligible peer returns 64 without advancing the generation.
        libpath=out/"block-host.so"
        run(["cc","-shared","-nostdlib","-o",libpath,objects["block"][0]])
        lib=ctypes.CDLL(str(libpath))
        fn=lib.hia_block_running
        fn.argtypes=[ctypes.c_uint64]*4
        fn.restype=ctypes.c_uint64
        cell=(ctypes.c_uint64*3)(0x11223344,0,0x55667788)
        addr=ctypes.addressof(cell)+8
        calls=0
        for n in range(1,33):
            for dep in range(n):
                for mask in (0,((1<<n)-1) ^ (1<<dep),1<<((dep+1)%n) if n>1 else 0):
                    for gen in (0,21,0xfffffffe):
                        before=(gen<<32)|mask
                        cell[1]=before
                        peers=[(dep+k)%n for k in range(1,n) if mask & (1<<((dep+k)%n))]
                        expected=peers[0] if peers else 64
                        after=((gen+1)<<32)|(mask & ~(1<<expected)) if peers else before
                        assert fn(addr,before,n,dep)==expected
                        assert cell[1]==after
                        cell[1]=before^(1<<32)
                        old=cell[1]
                        assert fn(addr,before,n,dep)==66
                        assert cell[1]==old
                        calls+=2
        for args in [(addr,1,1,0),(addr,4,2,0),(addr,2,0,0),(addr,2,33,0),(addr,2,2,2),(addr,(0xffffffff<<32)|2,2,0),(0,2,2,0),(addr+1,2,2,0)]:
            old=cell[1]
            assert fn(*args)==65,args
            assert cell[1]==old
            calls+=1
        assert cell[0]==0x11223344 and cell[2]==0x55667788
        record["host_running_block_calls"]=calls
        libpath=out/"idle-host.so"
        run(["cc","-shared","-nostdlib","-o",libpath,objects["idle"][0]])
        fn=ctypes.CDLL(str(libpath)).hia_idle_select
        fn.argtypes=[ctypes.c_uint64]*4
        fn.restype=ctypes.c_uint64
        cell=(ctypes.c_uint64*3)(0x12345678,0,0x23456789)
        addr=ctypes.addressof(cell)+8
        calls=0
        for n in range(2,33):
            idle=n-1
            for cur in range(n):
                eligible=((1<<idle)-1)&~(1<<cur)
                for bits in (0,eligible,eligible&-eligible):
                    for gen in (0,17,0xfffffffe):
                        before=(gen<<32)|bits
                        peers=[(cur+k)%n for k in range(1,n) if bits&(1<<((cur+k)%n))]
                        expected=peers[0] if peers else (64 if cur==idle else idle)
                        after=before if expected==64 else ((gen+1)<<32)|(bits&~(1<<expected))
                        cell[1]=before
                        assert fn(addr,before,n,cur)==expected,(n,cur,bits,gen)
                        assert cell[1]==after
                        cell[1]=before^(1<<32)
                        old=cell[1]
                        assert fn(addr,before,n,cur)==66
                        assert cell[1]==old
                        calls+=2
                cell[1]=0
                assert fn(addr,1<<idle,n,cur)==65
                assert cell[1]==0
                calls+=1
        for args in [(addr,0,1,0),(addr,0,33,0),(addr,0,2,2),(addr,1,2,0),(addr,0xffffffff<<32,2,0),(0,0,2,0),(addr+1,0,2,0)]:
            old=cell[1]
            assert fn(*args)==65,args
            assert cell[1]==old
            calls+=1
        assert cell[0]==0x12345678 and cell[2]==0x23456789
        record["host_idle_calls"]=calls
        libpath=out/"idle-comp-host.so"
        run(["cc","-shared","-nostdlib","-o",libpath,objects["idle_comp"][0]])
        fn=ctypes.CDLL(str(libpath)).hia_compensate_idle
        fn.argtypes=[ctypes.c_uint64]*5
        fn.restype=ctypes.c_uint64
        cell=(ctypes.c_uint64*3)(0x11223344,0,0x55667788)
        addr=ctypes.addressof(cell)+8
        calls=0
        for n in range(2,33):
            idle=n-1
            for cur in range(n):
                allowed=((1<<idle)-1)&~(1<<cur)
                masks={0,allowed}
                masks.update(1<<i for i in range(idle) if allowed&(1<<i))
                for mask in masks:
                    peers=[(cur+k)%n for k in range(1,n) if mask&(1<<((cur+k)%n))]
                    for gen in (0,23,0xfffffffd):
                        before=(gen<<32)|mask
                        if not peers and cur==idle:
                            cell[1]=before
                            assert fn(addr,before,n,cur,0)==65
                            assert cell[1]==before
                            calls+=1
                            continue
                        selected=peers[0] if peers else idle
                        after=((gen+1)<<32)|(mask&~(1<<selected))
                        restored=((gen+2)<<32)|mask
                        cell[1]=after
                        assert fn(addr,before,n,cur,selected)==0
                        assert cell[1]==restored
                        assert fn(addr,before,n,cur,selected)==66
                        assert cell[1]==restored
                        cell[1]=after^(1<<32)
                        old=cell[1]
                        assert fn(addr,before,n,cur,selected)==66
                        assert cell[1]==old
                        calls+=3
                        if len(peers)>1:
                            cell[1]=after
                            assert fn(addr,before,n,cur,peers[1])==65
                            assert cell[1]==after
                            calls+=1
        for args in [(addr,0,1,0,1),(addr,0,33,0,1),(addr,0,2,0,0),(addr,0,2,2,1),(addr,0,2,0,2),(addr,1,2,0,1),(addr,2,2,0,1),(addr,(0xfffffffe<<32),2,0,1),(0,0,2,0,1),(addr+1,0,2,0,1)]:
            old=cell[1]
            assert fn(*args)==65,args
            assert cell[1]==old
            calls+=1
        assert cell[0]==0x11223344 and cell[2]==0x55667788
        record["host_idle_compensation_calls"]=calls
        variants=[("short",None,None,False,33,b"P"),("long",None,None,True,33,b"P")]
        compensation=source_mutant("compensation",b'rollbackword:u64 = bit.or(rollbackhigh,bitmap)',b'rollbackword:u64 = bit.or(rollbackhigh,swapped)',"compensation-no-restore")
        variants.append(("compensation-no-restore","compensation",compensation,False,35,b"C"))
        guard=source_mutant("guard",b'match:bool = compare.eq(current,expected)',b'match:bool = compare.eq(expected,expected)',"guard-ignore-owner")
        variants.append(("guard-ignore-owner","guard",guard,False,35,b"F"))
        variants.append(("reverse-skip",None,None,False,35,b"F"))
        variants.append(("reverse-stale",None,None,False,35,b"Q"))
        no_undo=source_mutant("handoff",b'undone:u64 = call(bs,bf,bl,bt) {"function":"f1"}',b'undone:u64 = call(bs,bf,bl,bt) {"function":"f0"}',"reverse-no-undo")
        variants.append(("reverse-stale-no-undo","handoff",no_undo,False,35,b"F"))
        exchange=source_mutant("exchange",b'nextbits:u64 = bit.or(removed,outgoingbit)',b'nextbits:u64 = bit.or(removed,removed)',"exchange-no-requeue")
        variants.append(("exchange-no-requeue","exchange",exchange,False,35,b"X"))
        publisher=source_mutant("publisher",b'toggled:u64 = bit.xor(bitmap,marker)',b'toggled:u64 = bit.or(bitmap,bitmap)',"publisher-no-change")
        variants.append(("publisher-no-change","publisher",publisher,False,35,b"B"))
        dispatch=source_mutant("dispatch",b'match:bool = compare.eq(actual,expected)',b'match:bool = compare.eq(expected,expected)',"dispatch-ignore-live")
        variants.append(("dispatch-ignore-live","dispatch",dispatch,False,35,b"D"))
        wrong=source_mutant("owner",b'poff:u64 = int.shl.checked(ri,rshift)',b'poff:u64 = int.shl.checked(rs,rshift)',"owner-wrong-slot")
        variants.append(("owner-wrong-slot","owner",wrong,False,35,b"O"))
        cas=bytes.fromhex("f0480fb10a")
        code=objects["owner"][1]
        assert code.count(cas)==3
        # The final CAS belongs to the owner publication block. Verify instruction boundary.
        off=code.rindex(cas)
        dis=run(["objdump","-d",objects["owner"][0]]).decode()
        assert any(l.lstrip().startswith(f"{off:x}:") and "lock cmpxchg" in l for l in dis.splitlines())
        owner=machine_mutant("owner","owner-cas-nop",cas,off)
        variants.append(("owner-cas-nop","owner",owner,False,35,b"O"))
        code=objects["handoff"][1]
        assert code.count(cas)==6
        off=code.index(cas)
        dis=run(["objdump","-d",objects["handoff"][0]]).decode()
        assert any(l.lstrip().startswith(f"{off:x}:") and "lock cmpxchg" in l for l in dis.splitlines())
        handoff=machine_mutant("handoff","park-cas-nop",cas,off)
        variants.append(("park-cas-nop","handoff",handoff,False,35,b"H"))
        second=code.index(cas,off+len(cas))
        assert any(l.lstrip().startswith(f"{second:x}:") and "lock cmpxchg" in l for l in dis.splitlines())
        consume=machine_mutant("handoff","consume-cas-nop",cas,second)
        variants.append(("consume-cas-nop","handoff",consume,False,35,b"H"))
        # Change the exact native push r15 to push r14, without changing length.
        linked,code,export=objects["irq"]
        off=sym(linked,export)+21
        assert code[off:off+2]==b"\x41\x57"
        changed=code[:off]+b"\x41\x56"+code[off+2:]
        raw=out/"irq-save-wrong.text"; raw.write_bytes(changed)
        mutant=out/"irq-save-wrong.o"
        run(["objcopy","--update-section",".text="+str(raw),linked,mutant])
        assert text(mutant,out/"irq-save-wrong-readback.text")==changed
        record["objects"]["irq-save-wrong"]={"object_sha256":sha(mutant.read_bytes()),"text_sha256":sha(changed),"patched_offset":off}
        variants.append(("irq-save-wrong","irq",(mutant,changed,export),False,35,b"G"))
        irqenc=bytes.fromhex(qualification["kernel_irq"]["encoding_hex"])
        entry=sym(linked,export)
        assert code[entry:entry+len(irqenc)]==irqenc
        bad_iret=machine_mutant("irq","irq-iret-nop",b"\x48\xcf",entry+len(irqenc)-4)
        variants.append(("irq-iret-nop","irq",bad_iret,False,35,b"R"))
        requeue=source_mutant("block",b'nextbits:u64 = bit.or(removed,removed)',b'outgoingbit:u64 = int.shl.checked(one,outgoing)\n  nextbits:u64 = bit.or(removed,outgoingbit)',"block-requeues-running")
        variants += [("running-block-short",None,None,False,33,b"P"),("running-block-long",None,None,True,33,b"P"),("running-block-requeue","block",requeue,False,35,b"K")]
        noadvance=source_mutant("idle",b'iword:u64 = int.shl.checked(inext,ishift)',b'iword:u64 = int.shl.checked(igen,ishift)',"idle-no-advance")
        variants += [("idle-short",None,None,False,33,b"P"),("idle-long",None,None,True,33,b"P"),("idle-no-advance","idle",noadvance,False,35,b"I"),("idle-skip-hlt",None,None,False,35,b"I")]
        wrongstay=source_mutant("idle",b'nopeer:u64 = const() {"value":64}',b'nopeer:u64 = const() {"value":0}',"idle-stay-wrong-return")
        nostale=source_mutant("idle",b'live:u64 = x86.atomic.cmpxchg64(idaddr,idold,idold)',b'live:u64 = bit.or(idold,idold)',"idle-stay-no-identity")
        variants += [("idle-stay-short",None,None,False,33,b"P"),("idle-stay-long",None,None,True,33,b"P"),("idle-stay-wrong-return","idle",wrongstay,False,35,b"I"),("idle-stay-no-identity","idle",nostale,False,35,b"I")]
        badgen=source_mutant("idle_comp",b'restoregen:u64 = int.add.wrap(generation,twogen)',b'restoregen:u64 = int.add.wrap(generation,onegen)',"idle-rollback-no-advance")
        variants += [("idle-rollback-short",None,None,False,33,b"P"),("idle-rollback-long",None,None,True,33,b"P"),("idle-rollback-no-advance","idle_comp",badgen,False,35,b"I")]
        variants += [("idle-exit-rollback-short",None,None,False,33,b"P"),("idle-exit-rollback-long",None,None,True,33,b"P"),("idle-exit-rollback-skip-reverse",None,None,False,35,b"I")]
        wrongidle=source_mutant("policy",b'dr:u64 = call(ds,dw,dn,dc) {"function":"f6"}',b'dr:u64 = call(ds,dw,dn,dc) {"function":"f4"}',"policy-idle-as-block")
        wrongpreempt=source_mutant("policy",b'er:u64 = call(es,ew,en,ec) {"function":"f2"}',b'er:u64 = call(es,ew,en,ec) {"function":"f4"}',"policy-preempt-as-block")
        wrongblock=source_mutant("policy",b'kr:u64 = call(ks,kw,kn,kc) {"function":"f4"}',b'kr:u64 = call(ks,kw,kn,kc) {"function":"f2"}',"policy-block-as-preempt")
        variants += [("policy-preempt-short",None,None,False,33,b"P"),("policy-preempt-long",None,None,True,33,b"P"),("policy-block-short",None,None,False,33,b"P"),("policy-block-long",None,None,True,33,b"P"),("policy-idle-short",None,None,False,33,b"P"),("policy-idle-long",None,None,True,33,b"P"),("policy-idle-as-block","policy",wrongidle,False,35,b"I"),("policy-preempt-as-block","policy",wrongpreempt,False,35,b"X"),("policy-block-as-preempt","policy",wrongblock,False,35,b"K")]
        assert sources["reserved"].startswith(composed)
        rp=out/"reserved-host.so"
        run(["cc","-shared","-nostdlib","-o",rp,objects["reserved"][0]])
        reserved=ctypes.CDLL(str(rp)).hia_reserved_policy
        reserved.argtypes=[ctypes.c_uint64]*5
        reserved.restype=ctypes.c_uint64
        cell=(ctypes.c_uint64*3)(123,0,456)
        addr=ctypes.addressof(cell)+8
        calls=0
        for n in (1,2,3,4,5,8,32):
            for cur in range(n):
                for mask in (range(1<<n) if n<=8 else (0,1,2,1<<30,1<<31,0xffffffff,0x55555555,0xaaaaaaaa)):
                    for reason in (0,1,2,3):
                        for gen in (0,17,0xffffffff):
                            prior=(gen<<32)|mask
                            idle=n-1
                            bad=(n<2 or gen==0xffffffff or mask>>idle or mask&(1<<cur) or reason>2 or ((cur==idle)!=(reason==2)))
                            if bad: selected,new=65,prior
                            else:
                                choices=[(cur+k)%n for k in range(1,n) if mask&(1<<((cur+k)%n))]
                                if choices:
                                    selected=choices[0]
                                    bits=mask^(1<<selected)
                                    if reason==0: bits|=1<<cur
                                    new=((gen+1)<<32)|bits
                                elif reason==0: selected,new=cur,prior
                                elif cur==idle: selected,new=64,prior
                                else: selected,new=idle,(gen+1)<<32
                            cell[1]=prior
                            assert reserved(addr,prior,n,cur,reason)==selected,(n,cur,mask,reason,gen,selected)
                            assert cell[1]==new
                            calls+=1
                            if not bad:
                                cell[1]=prior^(1<<32)
                                observed=cell[1]
                                assert reserved(addr,prior,n,cur,reason)==66
                                assert cell[1]==observed
                                calls+=1
        assert (cell[0],cell[2])==(123,456)
        record["host_reserved_policy_calls"]=calls
        wrong=source_mutant("reserved",b'pr:u64 = call(ps,pw,pn,pc) {"function":"f2"}',b'pr:u64 = call(ps,pw,pn,pc) {"function":"f4"}',"reserved-preempt-as-block")
        variants += [("reserved-short",None,None,False,33,b"P"),("reserved-long",None,None,True,33,b"P"),("reserved-preempt-as-block","reserved",wrong,False,35,b"I")]
        compbase=b"hia-asm.v1 hepta.hia.program.kernel-tlb.v1 selfhost_elf\nexports(f0)\n"
        for k,m in (("compensation",{b"f0":b"f2"}),("idle_comp",{b"f0":b"f4",b"f1":b"f5"})):
            compbase+=re.sub(rb"\bf[01]\b",lambda x:m[x[0]],b"\n".join(sources[k].splitlines()[2:])+b"\n")
        assert sources["reserved_comp"].startswith(compbase)
        cp=out/"reserved-comp-host.so"
        run(["cc","-shared","-nostdlib","-o",cp,objects["reserved_comp"][0]])
        compensate=ctypes.CDLL(str(cp)).hia_reserved_compensation
        compensate.argtypes=[ctypes.c_uint64]*6
        compensate.restype=ctypes.c_uint64
        ccalls=0
        for n in (2,3,4,5,8,32):
            for cur in range(n):
                idle=n-1
                for mask in (range(1<<n) if n<=8 else (0,1,2,1<<30,1<<31,0xffffffff,0x55555555)):
                    for reason in (0,1,2,3):
                        for gen in (0,17,0xfffffffd,0xfffffffe):
                            prior=(gen<<32)|mask
                            choices=[(cur+k)%n for k in range(1,n) if mask&(1<<((cur+k)%n))]
                            target=choices[0] if choices else idle
                            bad=(gen>0xfffffffd or mask>>idle or mask&(1<<cur) or reason>2 or ((cur==idle)!=(reason==2)) or (not choices and (reason==0 or cur==idle)))
                            bits=(mask^(1<<target)) if choices else mask
                            if reason==0: bits|=1<<cur
                            after=((gen+1)<<32)|bits
                            restored=((gen+2)<<32)|mask
                            cell[1]=after
                            assert compensate(addr,prior,n,cur,target,reason)==(65 if bad else 0),(n,cur,mask,reason,gen,target)
                            assert cell[1]==(after if bad else restored)
                            ccalls+=1
                            if not bad:
                                assert compensate(addr,prior,n,cur,target,reason)==66
                                assert cell[1]==restored
                                ccalls+=1
                                for wrongtarget in range(n):
                                    if wrongtarget==target: continue
                                    cell[1]=after
                                    assert compensate(addr,prior,n,cur,wrongtarget,reason)==65
                                    assert cell[1]==after
                                    ccalls+=1
        assert (cell[0],cell[2])==(123,456)
        record["host_reserved_compensation_calls"]=ccalls
        wrongcomp=source_mutant("reserved_comp",b'cr:u64 = call(cs,cw,cn,cc,ct) {"function":"f2"}',b'cr:u64 = call(cs,cw,cn,cc,ct) {"function":"f4"}',"mixed-wrong-compensation")
        variants += [("mixed-comp-short",None,None,False,33,b"P"),("mixed-comp-long",None,None,True,33,b"P"),("mixed-comp-wrong-route","reserved_comp",wrongcomp,False,35,b"I"),("mixed-comp-skip-reverse",None,None,False,35,b"I")]
        badresolver=source_mutant("compose",b'found:bool = compare.ne(slot,rz)',b'found:bool = compare.eq(rz,rz)',"compose-bypass-resolver")
        wrongslot=source_mutant("compose",b'result:u64 = call(srcslot,xf,xh,xslot,xg,xj) {"function":"f4"}',b'result:u64 = call(xslot,xf,xh,xslot,xg,xj) {"function":"f4"}',"compose-alias-slots")
        variants += [("bounded-compose-short",None,None,False,33,b"P"),("bounded-compose-long",None,None,True,33,b"P"),("bounded-compose-bypass-resolver","compose",badresolver,False,35,b"H"),("bounded-compose-alias-slots","compose",wrongslot,False,35,b"H")]
        for name,key,mutant,long,rc,expected in variants:
            case=out/name; case.mkdir()
            obs=case/"observer.o"
            run(["cc","-m64","-c","-nostdlib","-fno-pie",*(["-DHIA_LONG"] if long else []),*(["-DHIA_IRQ_IRET_NOP",f"-DHIA_IRQ_TRAP_DELTA={len(irqenc)-2}"] if name=="irq-iret-nop" else []),*(["-DHIA_SKIP_REVERSE"] if name=="reverse-skip" else []),*(["-DHIA_REVERSE_STALE"] if name in ("reverse-stale","reverse-stale-no-undo") else []),*(["-DHIA_RUNNING_BLOCK"] if name.startswith(("running-block-","policy-block-")) else []),*(["-DHIA_IDLE_SKIP_HLT"] if name=="idle-skip-hlt" else []),*(["-DHIA_SKIP_IDLE_EXIT_REVERSE"] if name=="idle-exit-rollback-skip-reverse" else []),*(["-DHIA_MIXED_SKIP_REVERSE"] if name=="mixed-comp-skip-reverse" else []),ROOT/"tests/fixtures"/("x86_native_bounded_frame_compose.S" if name.startswith("bounded-compose-") else "x86_native_reserved_compensation.S" if name.startswith("mixed-comp-") else "x86_native_reserved_policy.S" if name.startswith("reserved-") else "x86_native_policy_idle.S" if name.startswith("policy-idle-") else "x86_native_policy_running.S" if name.startswith(("policy-preempt-","policy-block-")) else "x86_native_idle_exit_rollback.S" if name.startswith("idle-exit-rollback-") else "x86_native_idle_rollback.S" if name.startswith("idle-rollback-") else "x86_native_idle_stay.S" if name.startswith("idle-stay-") else "x86_native_idle_select.S" if name.startswith("idle-") else "x86_native_running_block.S"),"-o",obs])
            assert not any(op in run(["objdump","-d",obs]).decode().split() for op in ("iret","iretq","iretl"))
            inputs=dict(objects)
            if not name.startswith('bounded-compose-'): inputs.pop('compose')
            if key: inputs[key]=mutant
            guest=case/"guest.elf"; image=case/"guest32.elf"
            run(["ld","-nostdlib","-z","noexecstack","-z","max-page-size=0x1000","-T",ROOT/"tests/fixtures/x86_apic_one_shot_timer.ld","-o",guest,obs,*[v[0] for v in inputs.values()]])
            run(["objcopy","-O","elf32-i386",guest,image])
            gtext=text(guest,case/"guest.text")
            assert gtext==text(image,case/"guest32.text")
            sec=[r.split() for r in run(["objdump","-h",guest]).decode().splitlines() if len(r.split())>=6 and r.split()[1]==".text"]
            assert len(sec)==1
            base=int(sec[0][3],16)
            ranges=[]
            for obj,code,export in inputs.values():
                lo=sym(guest,export)-base-sym(obj,export)
                assert lo>=0 and gtext[lo:lo+len(code)]==code
                ranges.append((lo,lo+len(code)))
            ranges.sort()
            assert all(x[1]<=y[0] for x,y in zip(ranges,ranges[1:]))
            for machine in ("pc","q35"):
                row={"case":name,"machine":machine,"image_sha256":sha(image.read_bytes()),"expected_rc":rc,"expected_serial":expected.decode(),"status":"FAIL"}
                record["cases"].append(row)
                argv=["qemu-system-x86_64","-machine",machine,"-cpu","qemu64","-smp","1","-m","64M","-accel","tcg","-display","none","-serial","none","-monitor","none","-no-reboot","-no-shutdown","-device","isa-debug-exit,iobase=0xf4,iosize=0x04","-debugcon","stdio","-global","isa-debugcon.iobase=0xe9","-kernel",str(image)]
                r=subprocess.run(argv,capture_output=True,timeout=30)
                row.update(returncode=r.returncode,serial=r.stdout.decode(errors="replace"),stderr=r.stderr.decode(errors="replace")[-3000:])
                if (r.returncode,r.stdout)==(rc,expected): row["status"]="PASS"
                print(json.dumps(row),flush=True)
                assert row["status"]=="PASS",row
        record.update(native_bounded_frame_compose_forward_reverse=True,native_bounded_frame_compose_rejects_stale_and_bad_topology=True,native_reserved_compensation_all_four_switches=True,native_reserved_compensation_replay_refused=True,reserved_compensation_switches=4,reserved_compensation_rollbacks=4,reserved_compensation_ready_generation=13,native_reserved_topology_mixed_irq=True,reserved_switches=4,reserved_interrupts=6,native_policy_preempt_block_idle_dispatch=True,native_policy_actual_irq_routes=True,native_idle_exit_reverse_frame_and_ready_compensation=True,idle_exit_wakeup_bit_restored=True,idle_exit_compensation_replay_refused=True,idle_exit_ready_generation=8,native_idle_entry_reverse_frame_and_ready_compensation=True,idle_compensation_replay_refused=True,actual_idle_no_wake_irq_return_proved=True,idle_stay_stale_expected_refused=True,idle_stay_positive_switches=3,idle_stay_positive_interrupts=5,idle_stay_count=1,status="PASS",native_running_task_deferred_block_and_wake=True,actual_idle_transition_proved=True,idle_hlt_observed=True,idle_never_enqueued=True,idle_positive_switches=3,idle_positive_interrupts=4,native_reverse_handoff_after_owner_refusal=True,native_rollback_guard_rejects_stale_owner=True,reverse_stale_consume_fail_stop=True,ready_generation_preserved_after_reverse=True,native_ready_compensation_after_resolver_refusal=True,ready_compensation_stale_replay_refused=True,ready_compensation_preserves_monotonic_generation=True,native_three_task_preemption=True,native_bounded_slot_dispatch=True,native_owner_table_binding=True,native_ready_exchange_in_irq=True,native_block_and_wake=True,native_frame_handoff=True,native_owner_generation=True,stale_owner_replay_refused=True,owner_invalid_id_same_id_overflow_refused=True,native_gpr_capture_and_restore=True,native_iretq_return=True,actual_switches_per_positive=12,actual_interrupts_per_positive=13)
    finally:
        (out/"report.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps(record))
if __name__=="__main__": main()
