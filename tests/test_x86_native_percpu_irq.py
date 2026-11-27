#!/usr/bin/env python3
"""Native raw IRQ on both real QEMU CPUs with independently observed stack leases."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/x86_native_percpu_irq.hepta'
ENTRY=ROOT/'src/x86_native_scheduler_stack_entry.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_percpu_irq.S'
LINKER=ROOT/'tests/fixtures/x86_native_percpu_irq.ld'
COMPILER='434d32e6e7117796b0540cf635820dca9df10de012c60f7057f47aaffaa2f645'
COMPILER_SOURCE='8a4e5ca4b28cf2c0af4d2199b0ec7a0d32fea25ab6c13710c6c8cd1052a9e2f9'
SOURCE_SHA='b9edbbc6dd2b8dd91c12711b4a6746f35e0ef9131b59fabc14ed82770fa1c6b7'
OBJECT_SHA='f6dfacb9f119091bf3530b3614f904ffb8de9759c4242489c42825d13f97df88'
ENTRY_SHA='5e459438d43382b331f9a5f0717a4ecee10eb72598b6a2936e1ecd49667089a1'
ENTRY_OBJECT_SHA='1faf496fdb847b490d1e6f96325e94c220d32b161e74ae7dc00a8b204c1d474b'
def sha(b): return hashlib.sha256(b).hexdigest()
def run(argv,**kw):
    kw.setdefault('env',{**os.environ,'LC_ALL':'C'})
    return subprocess.run([str(x) for x in argv],check=True,capture_output=True,timeout=60,**kw).stdout
def code(p): return run(['objcopy','-O','binary','-j','.text',p,'/dev/stdout'])
def symbol(p,name):
    rows=[x.split() for x in run(['nm','-n',p]).decode().splitlines() if x.split()[-1:]==[name]]
    assert len(rows)==1,(name,rows)
    return int(rows[0][0],16)
def compile_pair(compiler,src,dest):
    b=run([compiler],input=src,env={'PATH':''})
    assert b==run([compiler],input=src,env={'PATH':''})
    dest.write_bytes(b)
    assert not run(['nm','-u',dest]).strip()
    assert b'There are no relocations' in run(['readelf','-Wr',dest])
    return b,code(dest)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--compiler-dir',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    c=a.compiler_dir.resolve(); out=a.output.resolve(); out.mkdir()
    compiler=c/'compiler-rebuilt-2'; report=json.loads((c/'report.json').read_text())
    assert report['status']=='PASS' and report['compiler_sha256']==COMPILER==sha(compiler.read_bytes())
    assert report['source_sha256']==COMPILER_SOURCE==sha((c/'candidate.hepta').read_bytes())
    src=SOURCE.read_bytes(); esrc=ENTRY.read_bytes()
    assert sha(src)==SOURCE_SHA and sha(esrc)==ENTRY_SHA
    eb,et=compile_pair(compiler,esrc,out/'entry.o'); assert sha(eb)==ENTRY_OBJECT_SHA
    entry=out/'entry-link.o'
    rows=[x.split() for x in run(['nm','-S',out/'entry.o']).decode().splitlines() if x.split()[-1:]==['f0']]
    assert len(rows)==1; end=int(rows[0][0],16)+int(rows[0][1],16)
    assert end<=len(et)
    run(['objcopy','--redefine-sym','f0=irq_entry','--add-symbol',f'irq_entry_end=.text:0x{end:x},global',out/'entry.o',entry])
    assert code(entry)==et
    def mutate(old,new):
        assert src.count(old)==1,(old,src.count(old)); return src.replace(old,new)
    variants=[('native',src,[],33,b'P'),
      ('no-epoch-publication',mutate(b'old:u64 = x86.atomic.cmpxchg64(qp,qg,next)',b'old:u64 = x86.atomic.cmpxchg64(qp,qg,qg)'),['-DHIA_SERIAL_NEGATIVE'],35,b'C'),
      ('no-eoi',mutate(b'_ = x86.mmio.write32(ea,z32)',b'_ = x86.fence.mfence()'),['-DHIA_SERIAL_NEGATIVE'],35,b'T'),
      ('wrong-return',mutate(b'branch same success(qf) bad()',b'branch same bad() success(qf)'),['-DHIA_SERIAL_NEGATIVE','-DHIA_POST_COMMIT_TRAP'],35,b'F'),
      ('wrong-live-gs',src,['-DHIA_SERIAL_NEGATIVE','-DHIA_WRONG_GS'],35,b'T'),
      ('ignore-live-gs',mutate(b'correct:bool = compare.eq(gs,desc)',b'correct:bool = compare.eq(desc,desc)'),['-DHIA_SERIAL_NEGATIVE','-DHIA_WRONG_GS'],35,b'Y'),
      ('epoch-exhausted',src,['-DHIA_SERIAL_NEGATIVE','-DHIA_EPOCH_EXHAUSTED'],35,b'T')]
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','compiler_sha256':COMPILER,'compiler_source_sha256':COMPILER_SOURCE,
         'entry_source_sha256':ENTRY_SHA,'entry_object_sha256':sha(eb),'entry_text_sha256':sha(et),
         'source_sha256':SOURCE_SHA,'observer_sha256':sha(BOOT.read_bytes()),'linker_sha256':sha(LINKER.read_bytes()),
         'general_cpu_authority_proved':False,'general_page_authority_proved':False,'general_smp_proved':False,
         'generation_bound_raw_entry_lease_proved':False,'actual_task_migration_proved':False,
         'simultaneous_independent_raw_irq_stacks_proved':False,'objects':{},'cases':[]}
    try:
        for name,source,flags,expected,serial in variants:
            d=out/name; d.mkdir(); obj=d/'callback.o'; binary,native=compile_pair(compiler,source,obj)
            if source==src: assert sha(binary)==OBJECT_SHA
            else: assert sha(binary)!=OBJECT_SHA
            rec['objects'][name]={'source_sha256':sha(source),'object_sha256':sha(binary),'text_sha256':sha(native)}
            observer=d/'observer.o'; guest=d/'guest.elf'; image=d/'guest32.elf'
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,BOOT,'-o',observer])
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',LINKER,'-o',guest,observer,obj,entry])
            run(['objcopy','-O','elf32-i386',guest,image]); actual=code(guest)
            rows=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text']; assert len(rows)==1
            start=int(rows[0][3],16)
            for sym,subject,text in [('f1',obj,native),('irq_entry',entry,et)]:
                off=symbol(guest,sym)-start-symbol(subject,sym)
                assert off>=0 and actual[off:off+len(text)]==text
            assert actual==code(image)
            for machine in ('pc','q35'):
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'guest_sha256':sha(guest.read_bytes()),'expected_rc':expected,'expected_serial':serial.decode(),'status':'FAIL'}; rec['cases'].append(row)
                try:
                    p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','2,sockets=1,cores=2,threads=1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],capture_output=True,timeout=25)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors='replace')); assert (p.returncode,p.stdout)==(expected,serial),row
                    row['status']='PASS'; print(machine,name,p.returncode,p.stdout,flush=True)
                except subprocess.TimeoutExpired:
                    row['status']='TIMEOUT'; raise
        assert SOURCE.read_bytes()==src and ENTRY.read_bytes()==esrc and sha(compiler.read_bytes())==COMPILER
        rec.update(status='PASS',simultaneous_independent_raw_irq_stacks_proved=True,exact_fixture_vcpus=2,irq_per_cpu=2,actual_native_eoi_and_same_frame_iretq=True)
    finally: (out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__': main()
