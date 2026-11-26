#!/usr/bin/env python3
"""Composed HIA PIT and calibrated APIC with exact subject and independent MMIO oracle."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/x86_apic_pit_reference.hepta"
BOOT = ROOT / "tests/fixtures/x86_apic_pit_reference.S"
LINKER = ROOT / "tests/fixtures/x86_apic_one_shot_timer.ld"
COMPILER_SHA = "753b55eda6fca1e74ad8bd81d6e4902f0ed673b3c2a58b0339af4f38d7581f58"
COMPILER_SOURCE_SHA = "240df3ba764066c4fb17cb8003f572dc6744e01c7891cbe7e4b940329b5a7fc1"


def digest(raw):
    return sha256(raw).hexdigest()


def run(argv, **kw):
    kw.setdefault("env", dict(os.environ, LC_ALL="C"))
    p = subprocess.run([str(x) for x in argv], capture_output=True, timeout=30, **kw)
    if p.returncode:
        raise AssertionError((argv, p.returncode, p.stdout[-2000:], p.stderr[-2000:]))
    return p.stdout


def extract(obj, raw):
    before = obj.read_bytes()
    discard = raw.with_suffix(".discard.o")
    run(["objcopy", "--dump-section", ".text=" + str(raw), obj, discard])
    discard.unlink()
    assert obj.read_bytes() == before
    return raw.read_bytes()


def symbol(obj, name):
    rows = [int(f[0], 16) for line in run(["nm", "-n", obj]).decode().splitlines()
            if len(f := line.split()) >= 3 and f[-1] == name]
    assert len(rows) == 1, (obj, name, rows)
    return rows[0]


def link(out, name, obj, expected, macro):
    case = out / name
    case.mkdir()
    observer, guest, image = (case / x for x in ("observer.o", "guest.elf", "guest32.elf"))
    flags = ["-D" + macro] if macro else []
    run(["cc", "-m64", "-c", "-nostdlib", "-fno-pie", *flags, BOOT, "-o", observer])
    run(["ld", "-nostdlib", "-z", "noexecstack", "-z", "max-page-size=0x1000",
         "-T", LINKER, "-o", guest, observer, obj])
    run(["objcopy", "-O", "elf32-i386", guest, image])
    rows = [line.split() for line in run(["objdump", "-h", guest]).decode().splitlines()
            if len(line.split()) >= 6 and line.split()[1] == ".text"]
    assert len(rows) == 1
    offset = symbol(guest, "f0") - int(rows[0][3], 16) - symbol(obj, "f0")
    assert offset >= 0
    text64 = extract(guest, case / "guest64.text")
    text32 = extract(image, case / "guest32.text")
    assert text64 == text32 and text64[offset:offset+len(expected)] == expected
    return image, {"guest64_sha256": digest(guest.read_bytes()),
                   "guest32_sha256": digest(image.read_bytes()),
                   "subject_text_offset": offset, "subject_text_sha256": digest(expected)}



def reference_count(s, l, ticks):
    if not s or not l or ticks not in (12000,24000) or not 3*s <= 2*l <= 5*s:
        return 0
    count = (2*s+l+2)//4 if ticks == 12000 else (2*s+l+1)//2
    return count if 1024 <= count <= 0x7fffffff else 0


def arithmetic_oracle(out, obj):
    # Only f2 is called in this disposable unprivileged native process.
    # Its reachable code is pure scalar arithmetic, not privileged I/O.
    lib = out / "pure-count.so"
    run(["ld", "-shared", "-z", "noexecstack", "-o", lib, obj])
    import random
    rng = random.Random(20261124)
    cases = [(s,l,t) for s in (0,1,1023,1024,1025,0x40000000,0x7fffffff,0x80000000,0xffffffff)
             for l in (0,1,1535,1536,2048,2560,0x7fffffff,0x80000000,0xffffffff)
             for t in (0,11999,12000,24000,24001)]
    for _ in range(1024):
        s = rng.randrange(0,1<<32)
        l = rng.randrange(0,1<<32)
        cases.append((s,l,12000 if rng.randrange(2)==0 else 24000))
        s = rng.randrange(1,1<<30)
        l = rng.randrange((3*s+1)//2,(5*s)//2+1)
        cases.extend(((s,l,12000),(s,l,24000)))
    expected = [[s,l,t,reference_count(s,l,t)] for s,l,t in cases]
    data = out / "arithmetic-cases.json"
    data.write_text(json.dumps(expected))
    runner = """import ctypes,json,sys
lib=ctypes.CDLL(sys.argv[1])
fn=lib.f2
fn.argtypes=[ctypes.c_uint32]*3
fn.restype=ctypes.c_uint32
rows=json.load(open(sys.argv[2]))
for s,l,t,wanted in rows:
    got=fn(s,l,t)
    assert got==wanted,(s,l,t,wanted,got)
"""
    result = subprocess.run([sys.executable,"-I","-c",runner,str(lib),str(data)],
                            capture_output=True,env={"PATH":""},timeout=30)
    (out/"arithmetic.stdout").write_bytes(result.stdout)
    (out/"arithmetic.stderr").write_bytes(result.stderr)
    assert result.returncode==0 and not result.stdout and not result.stderr, result.stderr
    return {"status":"PASS","native_calls":len(expected),"input_sha256":digest(data.read_bytes()),
            "valid":sum(r[-1]!=0 for r in expected),"rejected":sum(r[-1]==0 for r in expected)}


def decoded_rows(obj):
    for line in run(["objdump","-d","--show-raw-insn","--insn-width=16",obj]).decode().splitlines():
        m=re.match(r"^\s*(?:0x)?([0-9a-fA-F]+):\s+(.*?)\s*$",line)
        if not m:
            continue
        fields=m[2].split()
        n=0
        while n<len(fields) and re.fullmatch(r"[0-9a-fA-F]{2}",fields[n]):
            n+=1
        if n and n<len(fields):
            yield int(m[1],16),bytes.fromhex(" ".join(fields[:n])),fields[n],fields[n+1:]


def native_body_targets(obj,text):
    rows=list(decoded_rows(obj))
    exports={f"f{i}":symbol(obj,f"f{i}") for i in (*range(6),*range(7,12))}
    def calls(lo,hi):
        result=[]
        for at,raw,mnemonic,args in rows:
            if lo<=at<hi and mnemonic in ("call","callq"):
                assert len(raw)==5 and raw[0]==0xe8 and raw==text[at:at+5]
                target=at+5+int.from_bytes(raw[1:],"little",signed=True)
                assert args and target==int(args[0],16)
                result.append(target)
        return result
    entries={}
    for name,lo in exports.items():
        hi=min((v for v in exports.values() if v>lo),default=len(text))
        targets=calls(lo,hi)
        assert len(targets)==1,(name,targets)
        entries[name]=targets[0]
    end=min(exports.values())
    assert sorted(entries.values())==list(entries.values()) and entries["f0"]==0
    internal=calls(entries["f3"],entries["f4"])
    assert len(internal)==2 and entries["f2"] in internal
    private=next(t for t in internal if t!=entries["f2"])
    assert entries["f5"]<private<entries["f7"]
    entries["f6"]=private
    # The complete native PIT window calls all four actual PIT functions.
    assert calls(entries["f11"],end)==[entries[x] for x in ("f7","f8","f9","f10")]
    return entries,end,rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compiler-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    candidate = args.compiler_dir.resolve()
    report = json.loads((candidate / "report.json").read_bytes())
    compiler = candidate / "compiler-rebuilt-2"
    assert report["status"] == "PASS" and report["native_generations"] == 3 and report["empty_path_rebuilds"] == 2
    assert report["compiler_sha256"] == COMPILER_SHA == digest(compiler.read_bytes())
    assert report["source_sha256"] == COMPILER_SOURCE_SHA == digest((candidate / "candidate.hepta").read_bytes())
    source = SOURCE.read_bytes()
    # The composed HIA source must preserve both original qualified subjects
    # byte-for-byte except for export extension and ordered function renaming.
    apic = (ROOT / "src/x86_apic_calibrated_periodic.hepta").read_text()
    pit = (ROOT / "src/x86_pit_channel2.hepta").read_text()
    apic = apic.replace("exports(f0,f1,f2,f3,f4,f5)",
                        "exports(f0,f1,f2,f3,f4,f5,f7,f8,f9,f10,f11)",1)
    pit = "\n".join(pit.splitlines()[2:])+"\n"
    pit = re.sub(r"\bf([0-3])\b",lambda m:"f"+str(7+int(m[1])),pit)
    assert source.startswith((apic+pit+"fn f11(").encode())
    native = run([compiler], input=source, env={"PATH": ""})
    assert native.startswith(b"\x7fELF") and native == run([compiler], input=source, env={"PATH": ""})
    obj = out / "native.o"
    obj.write_bytes(native)
    assert not run(["nm", "-u", obj]).strip()
    relocs = run(["readelf", "-Wr", obj])
    (out / "relocations.txt").write_bytes(relocs)
    assert b"There are no relocations" in relocs and b"R_X86_64_" not in relocs
    text = extract(obj, out / "native.text")
    # The actual aligned MMIO write instruction is independently assembled.
    oracle = out / "oracle.S"
    oracle.write_text(".text\n testb $3,%dl\n jz 1f\n ud2\n1:\n movq -256(%rbp),%rax\n movl %eax,(%rdx)\n")
    run(["as", "--64", "-o", out / "oracle.o", oracle])
    write = extract(out / "oracle.o", out / "oracle.text")
    assert write == bytes.fromhex("f6c20374020f0b488b8500ffffff8902")
    # Bind the count-store mutation to the private arm implementation
    # actually called by f3. All other MMIO stores remain unchanged.
    entries, end, rows = native_body_targets(obj,text)
    indices=[i+14 for i in range(len(text)-15)
             if text[i:i+10]==write[:10] and text[i+14:i+16]==write[14:16]]
    assert len(indices)==9,indices
    private_writes=[i for i in indices if entries["f6"]<=i<end]
    assert len(private_writes)==3
    pos=private_writes[-1]
    assert any(at==pos and raw==write[-2:] and op.startswith("mov")
               for at,raw,op,args in rows)
    mutated=text[:pos]+b"\x90\x90"+text[pos+2:]
    badraw=out/"dynamic-count-nop.text"
    badraw.write_bytes(mutated)
    badobj=out/"dynamic-count-nop.o"
    run(["objcopy","--update-section",".text="+str(badraw),obj,badobj])
    assert extract(badobj,out/"dynamic-count-nop-readback.text")==mutated
    assert native_body_targets(badobj,mutated)[:2]==(entries,end)
    assert all(mutated[i:i+2]==text[i:i+2] for i in indices if i!=pos)
    arithmetic=arithmetic_oracle(out,obj)
    # Independently assemble and locate the one native PIT gate-start OUT.
    pit_oracle=out/"pit-oracle.S"
    pit_oracle.write_text(".text\n outb %al,(%dx)\n")
    run(["as","--64","-o",out/"pit-oracle.o",pit_oracle])
    pit_op=extract(out/"pit-oracle.o",out/"pit-oracle.text")
    assert pit_op==bytes.fromhex("ee")
    pit_writes=[at for at,raw,op,args in rows
                if entries["f8"]<=at<entries["f9"] and raw==pit_op and op in ("out","outb")]
    assert len(pit_writes)==1,pit_writes
    pit_pos=pit_writes[0]
    assert text[pit_pos:pit_pos+1]==pit_op
    pit_bad=text[:pit_pos]+b"\x90"+text[pit_pos+1:]
    pit_raw=out/"pit-start-nop.text"
    pit_raw.write_bytes(pit_bad)
    pit_obj=out/"pit-start-nop.o"
    run(["objcopy","--update-section",".text="+str(pit_raw),obj,pit_obj])
    assert extract(pit_obj,out/"pit-start-nop-readback.text")==pit_bad
    assert native_body_targets(pit_obj,pit_bad)[:2]==(entries,end)
    assert pit_bad[pos:pos+2]==text[pos:pos+2]
    assert mutated[pit_pos:pit_pos+1]==pit_op
    receipt = {"status":"FAIL", "compiler_sha256":COMPILER_SHA,
        "compiler_source_sha256":COMPILER_SOURCE_SHA,
        "subject_source_sha256":digest(source), "subject_object_sha256":digest(native),
        "subject_text_sha256":digest(text), "observer_sha256":digest(BOOT.read_bytes()),
        "linker_sha256":digest(LINKER.read_bytes()), "cases":[],
        "arithmetic":arithmetic, "native_body_entries":entries, "dynamic_count_store_offset":pos, "pit_gate_start_offset":pit_pos,
        "full_linux_acceptance":"HOLD", "production_toolchain_changed":False,
        "apic_authority_proved":False, "scheduler_clock_proved":False, "timer_teardown_native_hia":False, "periodic_timer_proved":False,
        "native_interrupt_entry_proved":False, "native_iretq_proved":False}
    try:
        for name, subject, code, macro, rc, serial in (
            ("calibrated-short",obj,text,None,33,b"P"),
            ("calibrated-long",obj,text,"HIA_TEST_LONG_PERIOD",33,b"P"),
            ("invalid-calibration",obj,text,"HIA_TEST_INVALID_ONLY",35,b"B"),
            ("dynamic-count-nop",badobj,mutated,"HIA_TEST_PERIODIC_COUNT_NOP",35,b"N"),
            ("pit-start-nop",pit_obj,pit_bad,"HIA_TEST_COMPOSE_PIT_START_NOP",35,b"G")):
            image, binding = link(out, name, subject, code, macro)
            for machine in ("pc","q35"):
                row = {"case":name,"machine":machine,**binding,"expected_rc":rc,
                       "expected_serial":serial.decode(),"status":"FAIL"}
                receipt["cases"].append(row)
                argv = ["qemu-system-x86_64","-machine",machine,"-cpu","qemu64",
                        "-smp","1","-m","64M","-accel","tcg","-display","none",
                        "-serial","none","-monitor","none","-no-reboot","-no-shutdown",
                        "-device","isa-debug-exit,iobase=0xf4,iosize=0x04",
                        "-debugcon","stdio","-global","isa-debugcon.iobase=0xe9","-kernel",str(image)]
                try:
                    p = subprocess.run(argv,capture_output=True,timeout=20)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors="replace"),
                               stderr=p.stderr.decode(errors="replace")[-3000:])
                    if name in ("calibrated-short","calibrated-long"):
                        assert p.returncode==rc and len(p.stdout)==57 and p.stdout[-1:]==serial,row
                        a,b,c,d,count,irqs,ticks=(int(p.stdout[i:i+8],16) for i in range(0,56,8))
                        assert 0<b<=a<=b*5//4 and 0<d<=c<=d*5//4,row
                        assert 3*b<=2*d<=5*b,row
                        assert ticks==(12000 if name=="calibrated-short" else 24000),row
                        assert count==reference_count(a,c,ticks) and count!=0,row
                        # Independently estimate expiries from the two raw MMIO
                        # references, not the HIA-calculated value alone.
                        numerator=5*(2*b+d)
                        denominator=4*count
                        lower=max(1,numerator//denominator-2)
                        upper=(numerator+denominator-1)//denominator+2
                        assert lower<=irqs<=upper,(row,irqs,lower,upper)
                        row.update(short_native=a,short_reference=b,long_native=c,long_reference=d,
                                   initial_count=count,requested_pit_ticks=ticks,window_pit_ticks=60000,
                                   window_irqs=irqs,independent_irq_count_bounds=[lower,upper])
                    else:
                        assert (p.returncode,p.stdout) == (rc,serial), row
                    row["status"]="PASS"
                except subprocess.TimeoutExpired:
                    row["status"]="TIMEOUT"
                    raise
        assert SOURCE.read_bytes() == source and obj.read_bytes() == native and digest(compiler.read_bytes()) == COMPILER_SHA
        receipt.update(status="PASS", masked_apic_calibration=True, native_sample_and_stop=True,
                       native_pit_two_windows=True, independent_apic_mmio_observer=True, calibrated_periodic_timer_proved=True,
                       dynamic_count_native=True, periodic_timer_proved=True, native_timer_mask_and_stop=True,
                       post_stop_pit_window_no_interrupts=True, scheduler_clock_proved=False,
                       native_pit_full_window=True, native_pit_budget_cleanup=True,
                       pit_gate_start_deleted_detected=True,
                       independent_external_clock_accuracy_proved=False)
    finally:
        (out / "report.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        print(json.dumps(receipt,sort_keys=True))

if __name__ == "__main__":
    main()
