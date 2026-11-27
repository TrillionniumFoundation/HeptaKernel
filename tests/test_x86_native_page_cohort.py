#!/usr/bin/env python3
"""Actual fixed two-CPU page retirement, revoke, ACK and reuse."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
import test_x86_native_generation_irq as parent
import test_x86_native_bound_irq as bound
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/x86_native_slab_physical.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_page_cohort.S'
COHORT=ROOT/'src/x86_native_page_cohort.hepta'
COHORT_SHA='66ef494bddcc1eaf2c2283a3b98cb6ed31a47af57c5612f68a56e17519c691c0'
COHORT_OBJECT_SHA='b8d060b532c84372597c32501f5163b118c1f92782cdfb0fedd79eb116dd348f'
ENTRY=ROOT/'src/x86_native_frame_slab_entry.hepta'
OWNER=ROOT/'src/x86_native_page_owner.hepta'
OWNER_SHA='55387ebc65a2687828f785b41ee2f56948aa8cdcfa99ee0f68c1df1f3f0236e3'
OWNER_OBJECT_SHA='3405a2bdbd2477e8aae5403fcd583f1803d72e0cbccd2cb21759d7d1e507e6c1'
COMPILER='b78a0a4475f71c027d86e2221737e052ad5dba6711eac3a4ddf6e9faeba775bd'
COMPILER_SOURCE='588d484529d5ea733d47073d4cf847a1834ea8087c18dcb0c159de343abd4233'
ENTRY_SHA='0bac0c0de11d8dde65e47dc6d54f001b894c43499698b9a09a55edeb47674f80'
ENTRY_OBJECT_SHA='5be25556efb5059236bef980fa5f9d8dd0b4587b2dec6c158026608cdd8bb986'
ENTRY_TEXT_SHA='8892c6b97f425fb22c9f7661df0eb6b54f4fd842ce288a4c74fcf1f76c2d4692'
SOURCE_SHA='15cb34719d4847928c37c1c53046aeed4eaac0dc795f1c0de6a4b1c8bbc71812'
OBJECT_SHA='3f40582e7ded5d2bbfddc231ac38f1c61ab57c150e4ab5ae17b5eacd0a0269d2'
sha,run,code,symbol,compile_pair=parent.sha,parent.run,parent.code,parent.symbol,parent.compile_pair
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--compiler-dir',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    c=a.compiler_dir.resolve();out=a.output.resolve();out.mkdir()
    compiler=c/'compiler-rebuilt-2'; report=json.loads((c/'report.json').read_text())
    assert report['status']=='PASS' and report['compiler_sha256']==COMPILER==sha(compiler.read_bytes())
    assert report['source_sha256']==COMPILER_SOURCE==sha((c/'candidate.hepta').read_bytes())
    src=SOURCE.read_bytes();assert sha(src)==SOURCE_SHA
    esrc=ENTRY.read_bytes();csrc=parent.SOURCE.read_bytes()
    assert sha(esrc)==ENTRY_SHA and sha(csrc)==parent.SOURCE_SHA
    eb,et=compile_pair(compiler,esrc,out/'entry.o');assert sha(eb)==ENTRY_OBJECT_SHA and sha(et)==ENTRY_TEXT_SHA
    cb,ct=compile_pair(compiler,csrc,out/'callback.o');assert sha(cb)==parent.OBJECT_SHA
    rows=[x.split() for x in run(['nm','-S',out/'entry.o']).decode().splitlines() if x.split()[-1:]==['f0']]
    assert len(rows)==1;end=int(rows[0][0],16)+int(rows[0][1],16);assert end<=len(et)
    patterns={'irq_binding_trap':'49c1e3054c01d84c39e074020f0b',
              'irq_root_trap':'b9000100c00f3248c1e2204809d04885c075020f0b','irq_slab_root_trap':'4c29d848a9ff0f000074020f0b','irq_slab_low_trap':'4d39dd74020f0b','irq_frame_pre_trap':'488d97a00000004839c2760e488d9000b000004839d773020f0b','irq_frame_post_trap':'4c89e0482500f0ffff498d97a00000004839c2760e488d9000b000004939d773020f0b'}
    syms={}
    for name,h in patterns.items():
        raw=bytes.fromhex(h);assert et.count(raw)==1;syms[name]=et.index(raw)+len(raw)-2
    assert syms['irq_root_trap']<syms['irq_binding_trap']<et.index(bytes.fromhex('498b442418a801'))
    assert eb.count(et)==1
    variants=[('native',[],33,'P','native'),
              ('bsp-first',['-DHIA_BSP_FIRST'],33,'P','native'),
              ('ap-first',['-DHIA_AP_FIRST'],33,'P','native'),
              ('early-reuse-bypass',['-DHIA_MUT_EARLY','-DHIA_BSP_FIRST'],35,'N','early'),
              ('revoke-cas-identity',['-DHIA_MUT_REVOKE','-DHIA_BSP_FIRST'],35,'N','revoke'),
              ('ack-cas-identity',['-DHIA_MUT_ACK','-DHIA_BSP_FIRST'],35,'N','ack'),
              ('remap-cas-identity',['-DHIA_MUT_REMAP','-DHIA_BSP_FIRST'],35,'N','remap'),
              ('publish-cas-identity',['-DHIA_MUT_PUBLISH','-DHIA_BSP_FIRST'],35,'N','publish')]
    mutations={'early':(b'v205:bool = compare.eq(v201,v204)',b'v205:bool = compare.eq(v201,v201)'),
               'revoke':(b'x86.atomic.cmpxchg64(v154,v155,v156)',b'x86.atomic.cmpxchg64(v154,v155,v155)'),
               'ack':(b'x86.atomic.cmpxchg64(v191,v192,v193)',b'x86.atomic.cmpxchg64(v191,v192,v192)'),
               'remap':(b'x86.atomic.cmpxchg64(v226,v229,v231)',b'x86.atomic.cmpxchg64(v226,v229,v229)'),
               'publish':(b'x86.atomic.cmpxchg64(v235,v236,v237)',b'x86.atomic.cmpxchg64(v235,v236,v236)')}
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','compiler_sha256':COMPILER,'compiler_source_sha256':COMPILER_SOURCE,'source_sha256':SOURCE_SHA,'observer_sha256':sha(BOOT.read_bytes()),'objects':{},'cases':[],'general_page_authority_proved':False,'concurrent_mutation_excluded':False,'ist_overflow_fault_proved_in_this_focus':False}
    owner_src=OWNER.read_bytes();assert sha(owner_src)==OWNER_SHA
    cohort_src=COHORT.read_bytes();assert sha(cohort_src)==COHORT_SHA
    try:
        for name,flags,expected,serial,mutant in variants:
            d=out/name;d.mkdir();subject=cohort_src
            if mutant!='native':
                old,new=mutations[mutant];assert subject.count(old)==1;subject=subject.replace(old,new)
            raw=bytearray(eb);entry_text=bytearray(et)
            (d/'entry-raw.o').write_bytes(raw);entry=d/'entry-link.o'
            args=['objcopy','--redefine-sym','f0=irq_entry']
            for k,v in syms.items():args+=['--add-symbol',f'{k}=.text:0x{v:x},global']
            args+=['--add-symbol',f'irq_entry_end=.text:0x{end:x},global',d/'entry-raw.o',entry]
            run(args);assert code(entry)==entry_text
            gb,gt=compile_pair(compiler,src,d/'guard.o');assert sha(gb)==OBJECT_SHA
            ob,ot=compile_pair(compiler,owner_src,d/'owner.o');assert sha(ob)==OWNER_OBJECT_SHA
            rb,rt=compile_pair(compiler,subject,d/'cohort.o')
            if mutant=='native':assert sha(rb)==COHORT_OBJECT_SHA
            else:assert sha(rb)!=COHORT_OBJECT_SHA
            reclaim=d/'cohort-link.o';run(['objcopy','--redefine-sym','f0=page_cohort',d/'cohort.o',reclaim]);assert code(reclaim)==rt
            owner=d/'owner-link.o';run(['objcopy','--redefine-sym','f0=page_owner',d/'owner.o',owner]);assert code(owner)==ot
            guard=d/'guard-link.o';run(['objcopy','--redefine-sym','f0=dual_guard',d/'guard.o',guard]);assert code(guard)==gt
            rec['objects'][name]={'source_sha256':sha(src),'object_sha256':sha(gb),'text_sha256':sha(gt),'cohort_source_sha256':sha(subject),'cohort_object_sha256':sha(rb),'cohort_text_sha256':sha(rt),'owner_source_sha256':sha(owner_src),'owner_object_sha256':sha(ob),'owner_text_sha256':sha(ot),'entry_object_sha256':sha(raw),'entry_text_sha256':sha(entry_text),'callback_object_sha256':sha(cb)}
            observer=d/'observer.o';guest=d/'guest.elf';image=d/'guest32.elf'
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,BOOT,'-o',observer])
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',parent.LINKER,'-o',guest,observer,out/'callback.o',entry,guard,owner,reclaim])
            run(['objcopy','-O','elf32-i386',guest,image]);actual=code(guest)
            rows=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text'];assert len(rows)==1
            start=int(rows[0][3],16)
            for sym,obj,txt in [('f1',out/'callback.o',ct),('irq_entry',entry,entry_text),('dual_guard',guard,gt),('page_owner',owner,ot),('page_cohort',reclaim,rt)]:
                off=symbol(guest,sym)-start-symbol(obj,sym);assert off>=0 and actual[off:off+len(txt)]==txt
            assert actual==code(image)
            assert symbol(guest,'slab')+45056<=2097152
            assert symbol(guest,'pool')==symbol(guest,'slab')+45056
            assert symbol(guest,'pool')+262144<=2097152
            arena=symbol(guest,'pool')
            tables=[symbol(guest,k) for k in ('pml4','pdpt','pd0','pd3','pt0')]
            assert all(not (arena<=t<arena+262144) for t in tables)
            assert OWNER.read_bytes()==owner_src
            for machine in ('pc','q35'):
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'guest_sha256':sha(guest.read_bytes()),'expected_rc':expected,'expected_serial':serial,'status':'FAIL'};rec['cases'].append(row)
                try:
                    p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','2,sockets=1,cores=2,threads=1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],stdin=subprocess.DEVNULL,capture_output=True,timeout=25)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors='replace'));assert (p.returncode,p.stdout)==(expected,serial.encode()),row
                    row['status']='PASS';print(machine,name,p.returncode,p.stdout,flush=True)
                except subprocess.TimeoutExpired:row['status']='TIMEOUT';raise
        assert SOURCE.read_bytes()==src and ENTRY.read_bytes()==esrc and parent.SOURCE.read_bytes()==csrc and sha(compiler.read_bytes())==COMPILER
        rec.update(status='PASS',fixed_two_cpu_revoke_ack_reuse_proved=True,missing_ack_reuse_refused=True,foreign_reuse_refused=True,old_generation_refused=True,both_cpu_real_page_faults=True,cohort_ack_bypass_control_detected=True,physical_reclamation_proved=False,general_page_authority_proved=False)
    finally:(out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
