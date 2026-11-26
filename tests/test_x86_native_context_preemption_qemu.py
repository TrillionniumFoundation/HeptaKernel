"""Compose exact native scheduling and restricted native integer-frame return."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
from test_x86_two_task_preemption_qemu import (
    ROOT, LINKER, digest, run, extract, symbol, native_body_targets, arithmetic_oracle)

SOURCE=ROOT/"src/x86_two_task_preemption.hepta"
RESTORE=ROOT/"src/x86_native_kernel_frame.hepta"
BOOT=ROOT/"tests/fixtures/x86_native_context_preemption.S"
COMPILER_SHA="ff22b8327b8c0e1c39abf59b2c0dcd4d6793ade8d73373cb2d5bd6132668f4e1"
COMPILER_SOURCE_SHA="0c2afe2ffcb3f0f8574ad3b27b6e0882cdb5b1869a3b713cfea84ba354aaf61b"
SCHEDULE_OBJECT_SHA="e3ff686aa2f6ae3f7698e1d61fe1fc42ef8e707cab2001635e76dc5d96f86381"
RESTORE_SOURCE_SHA="5f9e40d6960c4fd4acb69d0be0df4bce52b359ae6fa4ac1ac1a115246401caca"
RESTORE_OBJECT_SHA="dd2f89a4864066746d4229fa22745380e29b77ca65e323ddcb53115a3b46e419"


def link(out,name,scheduler,schedule_text,frame,frame_text,macros):
    p=out/name
    p.mkdir()
    renamed=p/"restore-renamed.o"
    # Only rename the one exported symbol. Never rewrite native instructions.
    run(["objcopy","--redefine-sym","f0=hia_restore_frame",frame,renamed])
    assert extract(renamed,p/"restore-renamed.text")==frame_text
    assert symbol(renamed,"hia_restore_frame")==symbol(frame,"f0")
    assert not run(["nm","-u",renamed]).strip()
    assert b"There are no relocations" in run(["readelf","-Wr",renamed])
    observer,guest,image=(p/x for x in ("observer.o","guest.elf","guest32.elf"))
    run(["cc","-m64","-c","-nostdlib","-fno-pie",*["-D"+x for x in macros],BOOT,"-o",observer])
    # IRQ entry is still assembly. It must not contain its own IRETQ.
    assert not any(op in run(["objdump","-d",observer]).decode().split() for op in ("iret","iretq","iretl"))
    run(["ld","-nostdlib","-z","noexecstack","-z","max-page-size=0x1000","-T",LINKER,
         "-o",guest,observer,scheduler,renamed])
    run(["objcopy","-O","elf32-i386",guest,image])
    rows=[l.split() for l in run(["objdump","-h",guest]).decode().splitlines()
          if len(l.split())>=6 and l.split()[1]==".text"]
    assert len(rows)==1
    vma=int(rows[0][3],16)
    a=symbol(guest,"f0")-vma-symbol(scheduler,"f0")
    b=symbol(guest,"hia_restore_frame")-vma-symbol(renamed,"hia_restore_frame")
    t64=extract(guest,p/"guest64.text")
    t32=extract(image,p/"guest32.text")
    assert t64==t32 and a>=0 and b>=0
    assert t64[a:a+len(schedule_text)]==schedule_text and t64[b:b+len(frame_text)]==frame_text
    assert a+len(schedule_text)<=b or b+len(frame_text)<=a
    return image,{"guest64_sha256":digest(guest.read_bytes()),"guest32_sha256":digest(image.read_bytes()),
                  "schedule_text_offset":a,"restore_text_offset":b,
                  "schedule_text_sha256":digest(schedule_text),"restore_text_sha256":digest(frame_text)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compiler-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    candidate=args.compiler_dir.resolve()
    report=json.loads((candidate/"report.json").read_bytes())
    compiler=candidate/"compiler-rebuilt-2"
    assert report["status"]=="PASS" and report["native_generations"]==3 and report["empty_path_rebuilds"]==2
    assert report["compiler_sha256"]==COMPILER_SHA==digest(compiler.read_bytes())
    assert report["source_sha256"]==COMPILER_SOURCE_SHA==digest((candidate/"candidate.hepta").read_bytes())
    source,restore=SOURCE.read_bytes(),RESTORE.read_bytes()
    assert digest(restore)==RESTORE_SOURCE_SHA==report["kernel_frame"]["source_sha256"]
    schedule=run([compiler],input=source,env={"PATH":""})
    frame=run([compiler],input=restore,env={"PATH":""})
    assert schedule==run([compiler],input=source,env={"PATH":""})
    assert frame==run([compiler],input=restore,env={"PATH":""})
    assert digest(schedule)==SCHEDULE_OBJECT_SHA
    assert digest(frame)==RESTORE_OBJECT_SHA==report["kernel_frame"]["elf_sha256"]
    sobj,fobj=out/"schedule.o",out/"restore.o"
    sobj.write_bytes(schedule);fobj.write_bytes(frame)
    for obj in (sobj,fobj):
        assert not run(["nm","-u",obj]).strip()
        assert b"There are no relocations" in run(["readelf","-Wr",obj])
    st=extract(sobj,out/"schedule.text")
    ft=extract(fobj,out/"restore.text")
    assert digest(ft)==report["kernel_frame"]["text_sha256"]
    entries,end,rows=native_body_targets(sobj,st)
    cas=bytes.fromhex("f0480fb10a")
    assert st.count(cas)==2 and st[entries["f13"]:end].count(cas)==1
    at=st.index(cas,entries["f13"],end)
    assert any(a==at and raw==cas and op=="lock" and args[0].startswith("cmpxchg") for a,raw,op,args in rows)
    tick=st.index(cas,entries["f12"],entries["f13"])
    encoding=bytes.fromhex(report["kernel_frame"]["encoding_hex"])
    assert len(encoding)==213 and ft.count(encoding)==1
    start=ft.index(encoding)
    delta=start+0xd3-symbol(fobj,"f0")

    def mutate(obj,text,label,at,original,replacement):
        assert text[at:at+len(original)]==original and len(original)==len(replacement)
        changed=text[:at]+replacement+text[at+len(original):]
        raw,target=out/(label+".text"),out/(label+".o")
        raw.write_bytes(changed)
        run(["objcopy","--update-section",".text="+str(raw),obj,target])
        assert extract(target,out/(label+"-readback.text"))==changed
        assert symbol(target,"f0")==symbol(obj,"f0")
        return target,changed

    badsched,bs=mutate(sobj,st,"schedule-cas-nop",at,cas,b"\x90"*len(cas))
    assert native_body_targets(badsched,bs)[:2]==(entries,end) and bs[tick:tick+len(cas)]==cas
    badiret,bi=mutate(fobj,ft,"restore-iret-nop",start+0xd1,b"\x48\xcf",b"\x90\x90")
    badgpr,bg=mutate(fobj,ft,"restore-r15-wrong",start+0xba,b"\x41\x5f",b"\x41\x5e")
    receipt={"status":"FAIL","compiler_sha256":COMPILER_SHA,"compiler_source_sha256":COMPILER_SOURCE_SHA,
             "schedule_source_sha256":digest(source),"schedule_object_sha256":digest(schedule),
             "schedule_text_sha256":digest(st),"restore_source_sha256":digest(restore),
             "restore_object_sha256":digest(frame),"restore_text_sha256":digest(ft),
             "observer_sha256":digest(BOOT.read_bytes()),"linker_sha256":digest(LINKER.read_bytes()),
             "arithmetic":arithmetic_oracle(out,sobj),"cases":[],
             "full_linux_acceptance":"HOLD","production_toolchain_changed":False,
             "native_interrupt_entry_proved":False,"arbitrary_context_restore_proved":False,
             "frame_resource_authority_proved":False,"fpu_context_proved":False,
             "general_scheduler_proved":False,"native_restore_used_in_actual_preemption":False}
    try:
        for name,s,scode,f,fcode,macros,rc,serial in (
            ("native-restore-short",sobj,st,fobj,ft,(),33,b"P"),
            ("native-restore-long",sobj,st,fobj,ft,("HIA_TEST_LONG_PERIOD",),33,b"P"),
            ("schedule-cas-nop",badsched,bs,fobj,ft,("HIA_TEST_SWITCH_CAS_NOP",),35,b"X"),
            ("restore-iret-nop",sobj,st,badiret,bi,("HIA_TEST_FRAME_IRET_NOP","HIA_TEST_FRAME_TRAP_DELTA="+str(delta)),35,b"R"),
            ("restore-r15-wrong",sobj,st,badgpr,bg,("HIA_TEST_FRAME_GPR_MUTANT",),35,b"Y")):
            image,binding=link(out,name,s,scode,f,fcode,macros)
            for machine in ("pc","q35"):
                row={"case":name,"machine":machine,**binding,"expected_rc":rc,
                     "expected_serial":serial.decode(),"status":"FAIL"}
                receipt["cases"].append(row)
                argv=["qemu-system-x86_64","-machine",machine,"-cpu","qemu64","-smp","1","-m","64M",
                      "-accel","tcg","-display","none","-serial","none","-monitor","none",
                      "-no-reboot","-no-shutdown","-device","isa-debug-exit,iobase=0xf4,iosize=0x04",
                      "-debugcon","stdio","-global","isa-debugcon.iobase=0xe9","-kernel",str(image)]
                try:
                    r=subprocess.run(argv,capture_output=True,timeout=20)
                    row.update(returncode=r.returncode,serial=r.stdout.decode(errors="replace"),
                               stderr=r.stderr.decode(errors="replace")[-3000:])
                    assert (r.returncode,r.stdout)==(rc,serial),row
                    row["status"]="PASS"
                except subprocess.TimeoutExpired:
                    row["status"]="TIMEOUT"
                    raise
        assert SOURCE.read_bytes()==source and RESTORE.read_bytes()==restore
        assert sobj.read_bytes()==schedule and fobj.read_bytes()==frame and digest(compiler.read_bytes())==COMPILER_SHA
        receipt.update(status="PASS",native_restore_used_in_actual_preemption=True,
                       native_quantum_task_selection=True,actual_two_task_preemption=True,
                       switches_per_positive=4,delivered_ticks_per_positive=9,
                       native_iretq_on_every_task_return=True,
                       schedule_cas_deleted_detected=True,restore_iret_deleted_detected=True,
                       wrong_gpr_restore_detected=True)
    finally:
        (out/"report.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        print(json.dumps(receipt,sort_keys=True))


if __name__=="__main__":
    main()
