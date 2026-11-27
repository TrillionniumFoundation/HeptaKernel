#!/usr/bin/env python3
"""Actual two-vCPU scheduler guards, pre-AP native two-leaf revocation."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
import test_x86_native_generation_irq as parent
import test_x86_native_bound_irq as bound
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/x86_native_dual_guard.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_bound_dual.S'
SOURCE_SHA='40d608198c8af41314ed5a03da84e58183758abcc1e9e4cb5e262d49077b2b6e'
OBJECT_SHA='139d5374dc369edd78330d1f07f383d50f2d15418f59288f9948fbf2953c9d98'
sha,run,code,symbol,compile_pair=parent.sha,parent.run,parent.code,parent.symbol,parent.compile_pair
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--compiler-dir',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    c=a.compiler_dir.resolve();out=a.output.resolve();out.mkdir()
    compiler=c/'compiler-rebuilt-2'; report=json.loads((c/'report.json').read_text())
    assert report['status']=='PASS' and report['compiler_sha256']==bound.COMPILER==sha(compiler.read_bytes())
    assert report['source_sha256']==bound.COMPILER_SOURCE==sha((c/'candidate.hepta').read_bytes())
    src=SOURCE.read_bytes();assert sha(src)==SOURCE_SHA
    esrc=bound.ENTRY.read_bytes();csrc=parent.SOURCE.read_bytes()
    assert sha(esrc)==bound.ENTRY_SHA and sha(csrc)==parent.SOURCE_SHA
    eb,et=compile_pair(compiler,esrc,out/'entry.o');assert sha(eb)==bound.ENTRY_OBJECT_SHA and sha(et)==bound.ENTRY_TEXT_SHA
    cb,ct=compile_pair(compiler,csrc,out/'callback.o');assert sha(cb)==parent.OBJECT_SHA
    rows=[x.split() for x in run(['nm','-S',out/'entry.o']).decode().splitlines() if x.split()[-1:]==['f0']]
    assert len(rows)==1;end=int(rows[0][0],16)+int(rows[0][1],16);assert end<=len(et)
    patterns={'irq_binding_trap':'49c1e3054c01d84c39e074020f0b',
              'irq_root_trap':'b9000100c00f3248c1e2204809d04885c075020f0b'}
    syms={}
    for name,h in patterns.items():
        raw=bytes.fromhex(h);assert et.count(raw)==1;syms[name]=et.index(raw)+len(raw)-2
    assert syms['irq_root_trap']<syms['irq_binding_trap']<et.index(bytes.fromhex('498b442418a801'))
    assert eb.count(et)==1
    variants=[('native',[],33,'P','native'),('bsp-fault',['-DHIA_PROBE_BSP'],35,'F','native'),('ap-fault',['-DHIA_PROBE_AP'],35,'H','native'),
      ('stale-first',['-DHIA_STALE_FIRST'],35,'D','native'),('second-alias',['-DHIA_SECOND_ALIAS'],35,'J','native'),
      ('skip-first',['-DHIA_PROBE_BSP'],35,'M','skip-first'),('skip-second',['-DHIA_PROBE_AP'],35,'M','skip-second'),
      ('partial-second',['-DHIA_PARTIAL_SECOND'],35,'T','partial-second'),
      ('wrong-bsp',['-DHIA_WRONG_BSP'],35,'D','native'),
      ('wrong-ap',['-DHIA_WRONG_AP'],35,'D','native'),
      ('wrong-root',['-DHIA_WRONG_ROOT'],35,'D','native'),
      ('ignore-binding-bsp',['-DHIA_WRONG_BSP'],35,'N','native'),
      ('ignore-binding-ap',['-DHIA_WRONG_AP'],35,'N','native'),
      ('bsp-ist-overflow',['-DHIA_IST_BSP'],35,'Q','native'),
      ('ap-ist-overflow',['-DHIA_IST_AP'],35,'U','native'),
      ('bsp-ist-mapped',['-DHIA_IST_BSP'],35,'O','skip-first'),
      ('ap-ist-mapped',['-DHIA_IST_AP'],35,'O','skip-second')]
    mutations={
      'skip-first':(b'  rc:u64 = call(rt,rf,ro) {"function":"f2"}',b'  rc:u64 = const() {"value":0}'),
      'skip-second':(b'  sc:u64 = call(tt,ts,tv) {"function":"f2"}',b'  sc:u64 = const() {"value":0}'),
      'partial-second':(b'  sc:u64 = call(tt,ts,tv) {"function":"f2"}',b'  pflags:u64 = const() {"value":3}\n  pwrong:u64 = bit.or(ts,pflags)\n  sc:u64 = call(tt,ts,pwrong) {"function":"f2"}')}
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','compiler_sha256':bound.COMPILER,'compiler_source_sha256':bound.COMPILER_SOURCE,'source_sha256':SOURCE_SHA,'observer_sha256':sha(BOOT.read_bytes()),'objects':{},'cases':[],'general_page_authority_proved':False,'concurrent_mutation_excluded':False,'ist_overflow_fault_proved':False}
    try:
        for name,flags,expected,serial,mutant in variants:
            d=out/name;d.mkdir();subject=src
            if mutant!='native':
                old,new=mutations[mutant];assert subject.count(old)==1;subject=subject.replace(old,new)
            raw=bytearray(eb);entry_text=bytearray(et)
            if name.startswith('ignore-binding'):
                at=syms['irq_binding_trap']-2;assert et[at]==0x74
                entry_text[at]=0xeb;raw[eb.index(et)+at]=0xeb
                assert sum(x!=y for x,y in zip(eb,raw))==1
            (d/'entry-raw.o').write_bytes(raw);entry=d/'entry-link.o'
            args=['objcopy','--redefine-sym','f0=irq_entry']
            for k,v in syms.items():args+=['--add-symbol',f'{k}=.text:0x{v:x},global']
            args+=['--add-symbol',f'irq_entry_end=.text:0x{end:x},global',d/'entry-raw.o',entry]
            run(args);assert code(entry)==entry_text
            if name.startswith(('wrong-','ignore-binding','bsp-ist','ap-ist')):flags=['-DHIA_SERIAL_NEGATIVE',*flags]
            gb,gt=compile_pair(compiler,subject,d/'guard.o')
            if mutant=='native':assert sha(gb)==OBJECT_SHA
            else:assert sha(gb)!=OBJECT_SHA
            guard=d/'guard-link.o';run(['objcopy','--redefine-sym','f0=dual_guard',d/'guard.o',guard]);assert code(guard)==gt
            rec['objects'][name]={'source_sha256':sha(subject),'object_sha256':sha(gb),'text_sha256':sha(gt),'entry_object_sha256':sha(raw),'entry_text_sha256':sha(entry_text),'callback_object_sha256':sha(cb)}
            observer=d/'observer.o';guest=d/'guest.elf';image=d/'guest32.elf'
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,BOOT,'-o',observer])
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',parent.LINKER,'-o',guest,observer,out/'callback.o',entry,guard])
            run(['objcopy','-O','elf32-i386',guest,image]);actual=code(guest)
            rows=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text'];assert len(rows)==1
            start=int(rows[0][3],16)
            for sym,obj,txt in [('f1',out/'callback.o',ct),('irq_entry',entry,entry_text),('dual_guard',guard,gt)]:
                off=symbol(guest,sym)-start-symbol(obj,sym);assert off>=0 and actual[off:off+len(txt)]==txt
            assert actual==code(image)
            assert symbol(guest,'slab')+45056<=2097152
            for machine in ('pc','q35'):
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'guest_sha256':sha(guest.read_bytes()),'expected_rc':expected,'expected_serial':serial,'status':'FAIL'};rec['cases'].append(row)
                try:
                    p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','2,sockets=1,cores=2,threads=1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],stdin=subprocess.DEVNULL,capture_output=True,timeout=25)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors='replace'));assert (p.returncode,p.stdout)==(expected,serial.encode()),row
                    row['status']='PASS';print(machine,name,p.returncode,p.stdout,flush=True)
                except subprocess.TimeoutExpired:row['status']='TIMEOUT';raise
        assert SOURCE.read_bytes()==src and bound.ENTRY.read_bytes()==esrc and parent.SOURCE.read_bytes()==csrc and sha(compiler.read_bytes())==bound.COMPILER
        rec.update(status='PASS',dual_native_guard_revocation_proved=True,actual_two_cpu_guard_faults_proved=True,simultaneous_guarded_scheduler_stacks_proved=True,preflight_no_mutation_proved=True,partial_failure_fail_closed=True,live_binding_and_dual_guards_same_image_proved=True,peer_free_negative_both_directions_proved=True,ist_overflow_fault_proved=True,independent_ist_stacks_both_cpus_proved=True)
    finally:(out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
