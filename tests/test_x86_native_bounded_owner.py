#!/usr/bin/env python3
"""Independent hardware observer for three fixed BSP tasks, not general SMP."""
import argparse, ctypes, hashlib, json, subprocess
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
        "owner":("x86_native_bounded_owner.hepta",{"f0":"hia_publish_bounded_owner"},None),
        "dispatch":("x86_native_bounded_slot_dispatch.hepta",{"f0":"hia_resolve_slot"},"c67bd59279dc31b097ffabaa330a0a58ea18f4416493b156d4fa6d1e0d4e9cd7"),
    }
    sources={name:(ROOT/"src"/path).read_bytes() for name,(path,_,_) in files.items()}
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
        record["host_dispatch_calls"]=host_dispatch_oracle()
        variants=[("short",None,None,False,33,b"P"),("long",None,None,True,33,b"P")]
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
        for name,key,mutant,long,rc,expected in variants:
            case=out/name; case.mkdir()
            obs=case/"observer.o"
            run(["cc","-m64","-c","-nostdlib","-fno-pie",*(["-DHIA_LONG"] if long else []),*(["-DHIA_IRQ_IRET_NOP",f"-DHIA_IRQ_TRAP_DELTA={len(irqenc)-2}"] if name=="irq-iret-nop" else []),ROOT/"tests/fixtures/x86_native_bounded_owner.S","-o",obs])
            assert not any(op in run(["objdump","-d",obs]).decode().split() for op in ("iret","iretq","iretl"))
            inputs=dict(objects)
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
        record.update(status="PASS",native_three_task_preemption=True,native_bounded_slot_dispatch=True,native_owner_table_binding=True,native_ready_exchange_in_irq=True,native_block_and_wake=True,native_frame_handoff=True,native_owner_generation=True,stale_owner_replay_refused=True,owner_invalid_id_same_id_overflow_refused=True,native_gpr_capture_and_restore=True,native_iretq_return=True,actual_switches_per_positive=12,actual_interrupts_per_positive=13)
    finally:
        (out/"report.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps(record))
if __name__=="__main__": main()
