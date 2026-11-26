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
BOOT=ROOT/"tests/fixtures/x86_native_frame_handoff_transaction.S"
HANDOFF=ROOT/"src/x86_native_frame_handoff_transaction.hepta"
IRQ=ROOT/"src/x86_native_irq_entry.hepta"
COMPILER_SHA="970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4"
COMPILER_SOURCE_SHA="42f8cccca8b084f42b40a30c3db19df1ffca069295d04666c5290f752e4a9715"
SCHEDULE_OBJECT_SHA="e3ff686aa2f6ae3f7698e1d61fe1fc42ef8e707cab2001635e76dc5d96f86381"
RESTORE_SOURCE_SHA="5f9e40d6960c4fd4acb69d0be0df4bce52b359ae6fa4ac1ac1a115246401caca"
RESTORE_OBJECT_SHA="dd2f89a4864066746d4229fa22745380e29b77ca65e323ddcb53115a3b46e419"


def link(out,name,scheduler,schedule_text,frame,frame_text,irq,irq_text,handoff,handoff_text,macros):
    p=out/name
    p.mkdir()
    renamed=p/"restore-renamed.o"
    # Only rename the one exported symbol. Never rewrite native instructions.
    run(["objcopy","--redefine-sym","f0=hia_restore_frame",frame,renamed])
    assert extract(renamed,p/"restore-renamed.text")==frame_text
    assert symbol(renamed,"hia_restore_frame")==symbol(frame,"f0")
    assert not run(["nm","-u",renamed]).strip()
    assert b"There are no relocations" in run(["readelf","-Wr",renamed])
    irq_renamed=p/"irq-renamed.o"
    run(["objcopy","--redefine-sym","f0=hia_irq_entry",irq,irq_renamed])
    assert extract(irq_renamed,p/"irq-renamed.text")==irq_text
    assert symbol(irq_renamed,"hia_irq_entry")==symbol(irq,"f0")
    assert not run(["nm","-u",irq_renamed]).strip()
    assert b"There are no relocations" in run(["readelf","-Wr",irq_renamed])
    handoff_renamed=p/"handoff-renamed.o"
    run(["objcopy","--redefine-sym","f0=hia_publish_frame","--redefine-sym","f1=hia_consume_frame","--redefine-sym","f2=hia_switch_frames",handoff,handoff_renamed])
    assert extract(handoff_renamed,p/"handoff-renamed.text")==handoff_text
    assert not run(["nm","-u",handoff_renamed]).strip()
    assert b"There are no relocations" in run(["readelf","-Wr",handoff_renamed])
    observer,guest,image=(p/x for x in ("observer.o","guest.elf","guest32.elf"))
    run(["cc","-m64","-c","-nostdlib","-fno-pie",*["-D"+x for x in macros],BOOT,"-o",observer])
    # The ordinary callback must not contain any IRET instruction.
    assert not any(op in run(["objdump","-d",observer]).decode().split() for op in ("iret","iretq","iretl"))
    run(["ld","-nostdlib","-z","noexecstack","-z","max-page-size=0x1000","-T",LINKER,
         "-o",guest,observer,scheduler,renamed,irq_renamed,handoff_renamed])
    run(["objcopy","-O","elf32-i386",guest,image])
    rows=[l.split() for l in run(["objdump","-h",guest]).decode().splitlines()
          if len(l.split())>=6 and l.split()[1]==".text"]
    assert len(rows)==1
    vma=int(rows[0][3],16)
    a=symbol(guest,"f0")-vma-symbol(scheduler,"f0")
    b=symbol(guest,"hia_restore_frame")-vma-symbol(renamed,"hia_restore_frame")
    c=symbol(guest,"hia_irq_entry")-vma-symbol(irq_renamed,"hia_irq_entry")
    t64=extract(guest,p/"guest64.text")
    t32=extract(image,p/"guest32.text")
    assert t64==t32 and a>=0 and b>=0
    assert t64[a:a+len(schedule_text)]==schedule_text and t64[b:b+len(frame_text)]==frame_text
    assert c>=0 and t64[c:c+len(irq_text)]==irq_text
    d=symbol(guest,"hia_publish_frame")-vma-symbol(handoff,"f0")
    assert d>=0 and t64[d:d+len(handoff_text)]==handoff_text
    intervals=sorted([(a,a+len(schedule_text)),(b,b+len(frame_text)),(c,c+len(irq_text)),(d,d+len(handoff_text))])
    assert all(x[1]<=y[0] for x,y in zip(intervals,intervals[1:]))
    return image,{"guest64_sha256":digest(guest.read_bytes()),"guest32_sha256":digest(image.read_bytes()),
                  "schedule_text_offset":a,"restore_text_offset":b,
                  "schedule_text_sha256":digest(schedule_text),"restore_text_sha256":digest(frame_text),
                  "irq_text_sha256":digest(irq_text),"irq_text_offset":c,"handoff_text_sha256":digest(handoff_text),"handoff_text_offset":d}


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
    irqsource=IRQ.read_bytes()
    assert digest(irqsource)==report["kernel_irq"]["source_sha256"]=="a64670a106e29d3a980c04421a776889b1b2e9a8146483f95a825862db83a986"
    assert digest(restore)==RESTORE_SOURCE_SHA==report["kernel_frame"]["source_sha256"]
    schedule=run([compiler],input=source,env={"PATH":""})
    frame=run([compiler],input=restore,env={"PATH":""})
    assert schedule==run([compiler],input=source,env={"PATH":""})
    assert frame==run([compiler],input=restore,env={"PATH":""})
    assert digest(schedule)==SCHEDULE_OBJECT_SHA
    assert digest(frame)==RESTORE_OBJECT_SHA==report["kernel_frame"]["elf_sha256"]
    irq=run([compiler],input=irqsource,env={"PATH":""})
    assert irq==run([compiler],input=irqsource,env={"PATH":""})
    assert digest(irq)==report["kernel_irq"]["elf_sha256"]=="f42b5bc59894dd99ec6bbb42f01e9ea2da4843931103e8438717cb9cb415331a"
    iobj=out/"irq.o";iobj.write_bytes(irq)
    sobj,fobj=out/"schedule.o",out/"restore.o"
    sobj.write_bytes(schedule);fobj.write_bytes(frame)
    handoff_source=HANDOFF.read_bytes()
    handoff=run([compiler],input=handoff_source,env={"PATH":""})
    assert handoff==run([compiler],input=handoff_source,env={"PATH":""})
    hobj=out/"handoff.o";hobj.write_bytes(handoff)
    for obj in (sobj,fobj,iobj,hobj):
        assert not run(["nm","-u",obj]).strip()
        assert b"There are no relocations" in run(["readelf","-Wr",obj])
    st=extract(sobj,out/"schedule.text")
    ft=extract(fobj,out/"restore.text")
    assert digest(ft)==report["kernel_frame"]["text_sha256"]
    it=extract(iobj,out/"irq.text")
    assert digest(it)==report["kernel_irq"]["text_sha256"]
    irqenc=bytes.fromhex(report["kernel_irq"]["encoding_hex"])
    ientry=symbol(iobj,"f0")
    assert it[ientry:ientry+len(irqenc)]==irqenc and it.count(irqenc)==1
    assert irqenc[:23]==bytes.fromhex("5053515256575541504151415241534154415541564157")
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
    badsave,bsi=mutate(iobj,it,"irq-r15-save-wrong",ientry+21,b"\x41\x57",b"\x41\x56")
    badirq,bii=mutate(iobj,it,"irq-iret-nop",ientry+len(irqenc)-4,b"\x48\xcf",b"\x90\x90")
    ht=extract(hobj,out/"handoff.text")
    from test_x86_two_task_preemption_qemu import decoded_rows
    hrows=list(decoded_rows(hobj))
    wrappers=[symbol(hobj,f"f{i}") for i in range(3)]
    starts=[]
    for lo,hi in zip(wrappers,wrappers[1:]+[len(ht)]):
        calls=[(a,raw,args) for a,raw,op,args in hrows if lo<=a<hi and op in ("call","callq")]
        assert len(calls)==1
        a,raw,args=calls[0]
        assert len(raw)==5 and raw[0]==0xe8 and ht[a:a+5]==raw
        target=a+5+int.from_bytes(raw[1:],"little",signed=True)
        assert target==int(args[0],16)
        starts.append(target)
    assert starts[0]==0<starts[1]<starts[2]<wrappers[0] and ht.count(cas)==2
    offsets=[]
    for lo,hi in zip(starts[:2],starts[1:]):
        assert ht[lo:hi].count(cas)==1
        pos=ht.index(cas,lo,hi)
        assert any(a==pos and raw==cas and op=="lock" and args[0].startswith("cmpxchg") for a,raw,op,args in hrows)
        offsets.append(pos)
    badpark,hp=mutate(hobj,ht,"park-cas-nop",offsets[0],cas,b"\x90"*len(cas))
    badunpark,hu=mutate(hobj,ht,"unpark-cas-nop",offsets[1],cas,b"\x90"*len(cas))
    assert hp[offsets[1]:offsets[1]+len(cas)]==cas
    assert hu[offsets[0]:offsets[0]+len(cas)]==cas
    receipt={"status":"FAIL","handoff_source_sha256":digest(handoff_source),"handoff_object_sha256":digest(handoff),
             "handoff_text_sha256":digest(ht),"handoff_cas_offsets":offsets,"native_frame_slot_lifecycle":False,"compiler_sha256":COMPILER_SHA,"compiler_source_sha256":COMPILER_SOURCE_SHA,
             "schedule_source_sha256":digest(source),"schedule_object_sha256":digest(schedule),
             "schedule_text_sha256":digest(st),"restore_source_sha256":digest(restore),
             "restore_object_sha256":digest(frame),"restore_text_sha256":digest(ft),
             "irq_source_sha256":digest(irqsource),"irq_object_sha256":digest(irq),"irq_text_sha256":digest(it),
             "observer_sha256":digest(BOOT.read_bytes()),"linker_sha256":digest(LINKER.read_bytes()),
             "arithmetic":arithmetic_oracle(out,sobj),"cases":[],
             "full_linux_acceptance":"HOLD","production_toolchain_changed":False,
             "native_interrupt_entry_proved":False,"arbitrary_context_restore_proved":False,
             "frame_resource_authority_proved":False,"fpu_context_proved":False,
             "general_scheduler_proved":False,"native_restore_used_in_actual_preemption":False,
             "native_composed_frame_handoff":False,"stale_target_rollback_proved":False,
             "missing_target_no_active_publication":False,"general_atomic_transaction_proved":False}
    try:
        for name,s,scode,f,fcode,i,icode,macros,rc,serial in (
            ("native-irq-short",sobj,st,fobj,ft,iobj,it,(),33,b"P"),
            ("native-irq-long",sobj,st,fobj,ft,iobj,it,("HIA_TEST_LONG_PERIOD",),33,b"P"),
            ("schedule-cas-nop",badsched,bs,fobj,ft,iobj,it,("HIA_TEST_SWITCH_CAS_NOP",),35,b"X"),
            ("restore-iret-nop",sobj,st,badiret,bi,iobj,it,("HIA_TEST_FRAME_IRET_NOP","HIA_TEST_FRAME_TRAP_DELTA="+str(delta)),35,b"R"),
            ("restore-r15-wrong",sobj,st,badgpr,bg,iobj,it,("HIA_TEST_FRAME_GPR_MUTANT",),35,b"Y"),
            ("irq-r15-save-wrong",sobj,st,fobj,ft,badsave,bsi,("HIA_TEST_IRQ_SAVE_MUTANT",),35,b"S"),
            ("irq-iret-nop",sobj,st,fobj,ft,badirq,bii,("HIA_TEST_IRQ_IRET_NOP","HIA_TEST_IRQ_TRAP_DELTA="+str(len(irqenc)-2)),35,b"I"),
            ("park-cas-nop",sobj,st,fobj,ft,iobj,it,("HIA_TEST_PARK_CAS_NOP",),35,b"V"),
            ("unpark-cas-nop",sobj,st,fobj,ft,iobj,it,("HIA_TEST_UNPARK_CAS_NOP",),35,b"W"),
            ("transaction-missing-destination",sobj,st,fobj,ft,iobj,it,("HIA_TEST_TX_MISSING",),35,b"T"),
            ("transaction-park-nop",sobj,st,fobj,ft,iobj,it,("HIA_TEST_TX_PARK_NOP",),35,b"D"),
            ("transaction-consume-nop",sobj,st,fobj,ft,iobj,it,("HIA_TEST_TX_CONSUME_NOP",),35,b"C")):
            h,hcode=(badpark,hp) if name in ("park-cas-nop","transaction-park-nop") else (badunpark,hu) if name in ("unpark-cas-nop","transaction-consume-nop") else (hobj,ht)
            image,binding=link(out,name,s,scode,f,fcode,i,icode,h,hcode,macros)
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
        assert SOURCE.read_bytes()==source and RESTORE.read_bytes()==restore and IRQ.read_bytes()==irqsource and iobj.read_bytes()==irq
        assert sobj.read_bytes()==schedule and fobj.read_bytes()==frame and digest(compiler.read_bytes())==COMPILER_SHA
        assert HANDOFF.read_bytes()==handoff_source and hobj.read_bytes()==handoff
        receipt.update(status="PASS",native_composed_frame_handoff=True,stale_target_rollback_proved=True,
                       missing_target_no_active_publication=True,native_frame_slot_lifecycle=True,park_and_unpark_cas_mutants_detected=True,native_interrupt_entry_proved=True,native_original_gpr_capture_on_every_tick=True,
                       native_irq_save_mutant_detected=True,native_irq_return_mutant_detected=True,
                       native_restore_used_in_actual_preemption=True,
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
