#!/usr/bin/env python3
"""Exact HIA CAS -> MFENCE -> INVLPG, real CPL0 NX instruction-fetch fault."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/x86_pt_atomic_exec_revoke.hepta"
BOOT=ROOT/"tests/fixtures/x86_pt_atomic_exec_revoke.S"
LINKER=ROOT/"tests/fixtures/x86_pt_atomic_write_protect.ld"
COMPILER_SHA="b8a57c604e749203f7403f932b5f5b333452303a1d5b11e6a9e7a9c8815bd98d"
COMPILER_SOURCE_SHA="2a09786d31834ca7bbf38fcff7280d43292cc5e082df8fcc7a584b836eb53e5a"

def digest(data): return sha256(data).hexdigest()

def run(argv, **kwargs):
    p=subprocess.run([str(a) for a in argv],capture_output=True,timeout=30,**kwargs)
    if p.returncode: raise AssertionError((argv,p.returncode,p.stdout[-2000:],p.stderr[-2000:]))
    return p.stdout

def extract(obj,raw):
    before=obj.read_bytes()
    discard=raw.with_suffix(".discard.o")
    run(["objcopy","--dump-section",".text="+str(raw),obj,discard])
    discard.unlink()
    assert obj.read_bytes()==before
    return raw.read_bytes()

def symbol(obj,name):
    rows=[int(f[0],16) for line in run(["nm","-n",obj]).decode().splitlines()
          if len(f:=line.split())>=3 and f[-1]==name]
    assert len(rows)==1,(obj,name,rows)
    return rows[0]

def link(out,name,obj,expected,macro):
    case=out/name
    case.mkdir()
    observer=case/"observer.o"
    guest=case/"guest.elf"
    image=case/"guest32.elf"
    flags=["-D"+macro] if macro else []
    run(["cc","-m64","-c","-nostdlib","-fno-pie",*flags,BOOT,"-o",observer])
    run(["ld","-nostdlib","-z","noexecstack","-z","max-page-size=0x1000","-T",LINKER,
         "-o",guest,observer,obj])
    run(["objcopy","-O","elf32-i386",guest,image])
    lines=run(["objdump","-h",guest]).decode().splitlines()
    rows=[line.split() for line in lines if len(line.split())>=6 and line.split()[1]==".text"]
    assert len(rows)==1
    offset=symbol(guest,"f0")-int(rows[0][3],16)-symbol(obj,"f0")
    assert offset>=0
    text64=extract(guest,case/"guest64.text")
    text32=extract(image,case/"guest32.text")
    assert text64==text32 and text64[offset:offset+len(expected)]==expected
    return image,{"guest64_sha256":digest(guest.read_bytes()),"guest32_sha256":digest(image.read_bytes()),
                  "subject_text_offset":offset,"subject_text_sha256":digest(expected)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--compiler-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    candidate=args.compiler_dir.resolve()
    report=json.loads((candidate/"report.json").read_bytes())
    compiler=candidate/"compiler-rebuilt-2"
    assert report["status"]=="PASS" and report["native_generations"]==3 and report["empty_path_rebuilds"]==2
    assert report["compiler_sha256"]==COMPILER_SHA==digest(compiler.read_bytes())
    assert report["source_sha256"]==COMPILER_SOURCE_SHA==digest((candidate/"candidate.hepta").read_bytes())
    source=SOURCE.read_bytes()
    native=run([compiler],input=source,env={"PATH":""})
    assert native.startswith(b"\x7fELF") and native==run([compiler],input=source,env={"PATH":""})
    obj=out/"native.o";obj.write_bytes(native)
    assert not run(["nm","-u",obj]).strip()
    relocs=run(["readelf","-Wr",obj])
    (out/"relocations.txt").write_bytes(relocs)
    assert b"There are no relocations" in relocs and b"R_X86_64_" not in relocs
    text=extract(obj,out/"native.text")
    oracle=out/"oracle.S"
    oracle.write_text(".text\n lock cmpxchgq %rcx,(%rdx)\n mfence\n invlpg (%rax)\n")
    run(["as","--64","-o",out/"oracle.o",oracle])
    opcode=extract(out/"oracle.o",out/"oracle.text")
    assert opcode==bytes.fromhex("f0480fb10a0faef00f0138")
    cas,fence,invlpg=opcode[:5],opcode[5:8],opcode[8:]
    assert all(text.count(x)==1 for x in (cas,fence,invlpg))
    assert text.index(cas)<text.index(fence)<text.index(invlpg)
    mutated=text.replace(cas,b"\x90"*len(cas),1)
    badraw=out/"cas-nop.text";badraw.write_bytes(mutated)
    badobj=out/"cas-nop.o"
    run(["objcopy","--update-section",".text="+str(badraw),obj,badobj])
    assert extract(badobj,out/"cas-nop-readback.text")==mutated and symbol(obj,"f0")==symbol(badobj,"f0")
    receipt={"status":"FAIL","compiler_sha256":COMPILER_SHA,"compiler_source_sha256":COMPILER_SOURCE_SHA,
             "subject_source_sha256":digest(source),"subject_object_sha256":digest(native),
             "subject_text_sha256":digest(text),"observer_sha256":digest(BOOT.read_bytes()),
             "linker_sha256":digest(LINKER.read_bytes()),"cases":[],
             "full_linux_acceptance":"HOLD","production_toolchain_changed":False,
             "authority_proved":False,"remote_shootdown_proved":False,
             "transition":"present-RO-X-to-present-RO-NX","expected_fault_error":17}
    try:
        for name,subject,code,macro,rc,serial in (
            ("nx-fetch-fault",obj,text,None,33,b"P"),
            ("stale",obj,text,"HIA_TEST_STALE",35,b"S"),
            ("bad-caps",obj,text,"HIA_TEST_BAD_CAPS",35,b"C"),
            ("bad-address",obj,text,"HIA_TEST_BAD_ADDRESS",35,b"B"),
            ("bad-transition",obj,text,"HIA_TEST_BAD_TRANSITION",35,b"T"),
            ("already-nx",obj,text,"HIA_TEST_ALREADY_NX",35,b"T"),
            ("restore",obj,text,"HIA_TEST_RESTORE",35,b"R"),
            ("cas-nop",badobj,mutated,None,35,b"N")):
            image,binding=link(out,name,subject,code,macro)
            for machine in ("pc","q35"):
                row={"case":name,"machine":machine,**binding,"expected_rc":rc,
                     "expected_serial":serial.decode(),"status":"FAIL"}
                receipt["cases"].append(row)
                argv=["qemu-system-x86_64","-machine",machine,"-cpu","qemu64","-m","64M",
                      "-accel","tcg","-display","none","-serial","none","-monitor","none",
                      "-no-reboot","-no-shutdown","-device","isa-debug-exit,iobase=0xf4,iosize=0x04",
                      "-debugcon","stdio","-global","isa-debugcon.iobase=0xe9","-kernel",str(image)]
                try:
                    p=subprocess.run(argv,capture_output=True,timeout=20)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors="replace"),
                               stderr=p.stderr.decode(errors="replace")[-3000:])
                    assert (p.returncode,p.stdout)==(rc,serial),row
                    row["status"]="PASS"
                except subprocess.TimeoutExpired:
                    row["status"]="TIMEOUT"
                    raise
        assert SOURCE.read_bytes()==source and obj.read_bytes()==native and digest(compiler.read_bytes())==COMPILER_SHA
        receipt["status"]="PASS"
    finally:
        (out/"report.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        print(json.dumps(receipt,sort_keys=True))

if __name__=="__main__": main()
