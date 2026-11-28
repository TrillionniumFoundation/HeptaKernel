#!/usr/bin/env python3
"""Actual two-vCPU scheduler guards, pre-AP native two-leaf revocation."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
import test_x86_native_generation_irq as parent
import test_x86_native_bound_irq as bound
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/x86_native_dual_guard.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_frame_slab.S'
ENTRY=ROOT/'src/x86_native_frame_slab_entry.hepta'
COMPILER='b78a0a4475f71c027d86e2221737e052ad5dba6711eac3a4ddf6e9faeba775bd'
COMPILER_SOURCE='588d484529d5ea733d47073d4cf847a1834ea8087c18dcb0c159de343abd4233'
ENTRY_SHA='0bac0c0de11d8dde65e47dc6d54f001b894c43499698b9a09a55edeb47674f80'
ENTRY_OBJECT_SHA='5be25556efb5059236bef980fa5f9d8dd0b4587b2dec6c158026608cdd8bb986'
ENTRY_TEXT_SHA='8892c6b97f425fb22c9f7661df0eb6b54f4fd842ce288a4c74fcf1f76c2d4692'
SOURCE_SHA='40d608198c8af41314ed5a03da84e58183758abcc1e9e4cb5e262d49077b2b6e'
OBJECT_SHA='139d5374dc369edd78330d1f07f383d50f2d15418f59288f9948fbf2953c9d98'
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
    variants=[('native',[],33,'P','native')]
    for stage,marker in (('pre','D'),('post','F')):
        for cpu in ('bsp','ap'):
            flags=['-DHIA_'+stage.upper()+'_'+cpu.upper()]
            variants.append((stage+'-'+cpu,flags,35,marker,'native'))
            variants.append(('ignore-'+stage+'-'+cpu,flags,35,'N','native'))
    mutations={
      'skip-first':(b'  rc:u64 = call(rt,rf,ro) {"function":"f2"}',b'  rc:u64 = const() {"value":0}'),
      'skip-second':(b'  sc:u64 = call(tt,ts,tv) {"function":"f2"}',b'  sc:u64 = const() {"value":0}'),
      'partial-second':(b'  sc:u64 = call(tt,ts,tv) {"function":"f2"}',b'  pflags:u64 = const() {"value":3}\n  pwrong:u64 = bit.or(ts,pflags)\n  sc:u64 = call(tt,ts,pwrong) {"function":"f2"}')}
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','compiler_sha256':COMPILER,'compiler_source_sha256':COMPILER_SOURCE,'source_sha256':SOURCE_SHA,'observer_sha256':sha(BOOT.read_bytes()),'objects':{},'cases':[],'general_page_authority_proved':False,'concurrent_mutation_excluded':False,'ist_overflow_fault_proved_in_this_focus':False}
    try:
        for name,flags,expected,serial,mutant in variants:
            d=out/name;d.mkdir();subject=src
            if mutant!='native':
                old,new=mutations[mutant];assert subject.count(old)==1;subject=subject.replace(old,new)
            raw=bytearray(eb);entry_text=bytearray(et)
            if name.startswith('ignore-'):
                at=syms['irq_frame_'+name.split('-')[1]+'_trap']-2;assert et[at]==0x73
                entry_text[at]=0xeb;raw[eb.index(et)+at]=0xeb
                assert sum(x!=y for x,y in zip(eb,raw))==1
            (d/'entry-raw.o').write_bytes(raw);entry=d/'entry-link.o'
            args=['objcopy','--redefine-sym','f0=irq_entry']
            for k,v in syms.items():args+=['--add-symbol',f'{k}=.text:0x{v:x},global']
            args+=['--add-symbol',f'irq_entry_end=.text:0x{end:x},global',d/'entry-raw.o',entry]
            run(args);assert code(entry)==entry_text
            if name!='native':flags=['-DHIA_SERIAL_NEGATIVE',*flags]
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
        assert SOURCE.read_bytes()==src and ENTRY.read_bytes()==esrc and parent.SOURCE.read_bytes()==csrc and sha(compiler.read_bytes())==COMPILER
        rec.update(status='PASS',full_slab_interrupted_frame_exclusion_proved=True,full_slab_selected_frame_exclusion_proved=True,pre_guard_bypass_observed_peer_frame=True,post_guard_bypass_observed_real_iret=True)
    finally:(out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
