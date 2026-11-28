#!/usr/bin/env python3
"""Actual native pre-lease live xAPIC / independent FS-root / GS binding."""
import argparse, json, subprocess
from pathlib import Path
import test_x86_native_generation_irq as parent
ROOT=Path(__file__).resolve().parents[1]
ENTRY=ROOT/'src/x86_native_bound_irq_entry.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_bound_irq.S'
sha,run,code,symbol,compile_pair=parent.sha,parent.run,parent.code,parent.symbol,parent.compile_pair
COMPILER='d9e483828e77f800f4f8b5bdaf017d48d19df67746147fdc3137c23be03edd81'
COMPILER_SOURCE='3e38d3591cdb13e00b68037089285afbee275c3d80bfacc5bf644fd7d5364eee'
ENTRY_SHA='e2424cba5033f8e690aad0148243854c879e0376649044a222ad88a2d4ea17d3'
ENTRY_OBJECT_SHA='2416ada4d28f8d2fa6c3b685965c51d2eefa33a6086b81d0acbdd81c251bdc81'
ENTRY_TEXT_SHA='83775e2fb98de051f1967965d3e57c746cef6eddd90293a4ce98f7e9557691a3'
def main():
    p=argparse.ArgumentParser();p.add_argument('--compiler-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    c=a.compiler_dir.resolve();out=a.output.resolve();out.mkdir()
    exe=c/'compiler-rebuilt-2';report=json.loads((c/'report.json').read_text())
    assert report['status']=='PASS' and report['compiler_sha256']==COMPILER==sha(exe.read_bytes())
    assert report['source_sha256']==COMPILER_SOURCE==sha((c/'candidate.hepta').read_bytes())
    es=ENTRY.read_bytes();cs=parent.SOURCE.read_bytes()
    assert sha(es)==ENTRY_SHA and sha(cs)==parent.SOURCE_SHA
    eb,et=compile_pair(exe,es,out/'entry.o');assert sha(eb)==ENTRY_OBJECT_SHA and sha(et)==ENTRY_TEXT_SHA
    cb,ct=compile_pair(exe,cs,out/'callback.o');assert sha(cb)==parent.OBJECT_SHA
    patterns={'irq_binding_trap':'49c1e3054c01d84c39e074020f0b',
      'irq_root_trap':'b9000100c00f3248c1e2204809d04885c075020f0b'}
    syms={}
    for name,h in patterns.items():
        b=bytes.fromhex(h);assert et.count(b)==1,(name,et.count(b));syms[name]=et.index(b)+len(b)-2
    assert syms['irq_root_trap']<syms['irq_binding_trap']<et.index(bytes.fromhex('498b442418a801'))
    rows=[x.split() for x in run(['nm','-S',out/'entry.o']).decode().splitlines() if x.split()[-1:]==['f0']]
    assert len(rows)==1;end=int(rows[0][0],16)+int(rows[0][1],16);assert end<=len(et)
    variants=[('native',[],33,'P',False),('wrong-bsp',['-DHIA_WRONG_BSP'],35,'D',False),('wrong-ap',['-DHIA_WRONG_AP'],35,'D',False),('wrong-root',['-DHIA_WRONG_ROOT'],35,'D',False),('ignore-binding-bsp',['-DHIA_WRONG_BSP'],35,'N',True),('ignore-binding-ap',['-DHIA_WRONG_AP'],35,'N',True)]
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','compiler_sha256':COMPILER,'compiler_source_sha256':COMPILER_SOURCE,'entry_source_sha256':ENTRY_SHA,'entry_object_sha256':sha(eb),'entry_text_sha256':sha(et),'callback_source_sha256':sha(cs),'callback_object_sha256':sha(cb),'observer_sha256':sha(BOOT.read_bytes()),'objects':{},'cases':[],'general_cpu_authority_proved':False,'general_page_authority_proved':False}
    try:
        for name,flags,rc,serial,mut in variants:
            d=out/name;d.mkdir(); raw=bytearray(eb);text=bytearray(et)
            if mut:
                at=syms['irq_binding_trap']-2
                assert text[at]==0x74 and eb.count(et)==1
                text[at]=0xeb;raw[eb.index(et)+at]=0xeb
                assert sum(x!=y for x,y in zip(eb,raw))==1
            obj=d/'entry-raw.o';obj.write_bytes(raw);entry=d/'entry.o'
            args=['objcopy','--redefine-sym','f0=irq_entry']
            for k,v in syms.items():args+=['--add-symbol',f'{k}=.text:0x{v:x},global']
            args+=['--add-symbol',f'irq_entry_end=.text:0x{end:x},global',obj,entry]
            run(args);assert code(entry)==text
            rec['objects'][name]={'entry_object_sha256':sha(raw),'entry_text_sha256':sha(text),'callback_object_sha256':sha(cb),'callback_text_sha256':sha(ct)}
            if name!='native':flags=['-DHIA_SERIAL_NEGATIVE',*flags]
            observer=d/'observer.o';guest=d/'guest.elf';image=d/'guest32.elf'
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,BOOT,'-o',observer])
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',parent.LINKER,'-o',guest,observer,out/'callback.o',entry])
            run(['objcopy','-O','elf32-i386',guest,image]);actual=code(guest)
            rows=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text'];assert len(rows)==1
            start=int(rows[0][3],16)
            for sym,o,expected in [('f1',out/'callback.o',ct),('irq_entry',entry,text)]:
                off=symbol(guest,sym)-start-symbol(o,sym);assert off>=0 and actual[off:off+len(expected)]==expected
            assert actual==code(image)
            for machine in ('pc','q35'):
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'guest_sha256':sha(guest.read_bytes()),'expected_rc':rc,'expected_serial':serial,'status':'FAIL'};rec['cases'].append(row)
                try:
                    proc=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','2,sockets=1,cores=2,threads=1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],stdin=subprocess.DEVNULL,capture_output=True,timeout=25)
                    row.update(returncode=proc.returncode,serial=proc.stdout.decode(errors='replace'));assert (proc.returncode,proc.stdout)==(rc,serial.encode()),row
                    row['status']='PASS';print(machine,name,proc.returncode,proc.stdout,flush=True)
                except subprocess.TimeoutExpired:row['status']='TIMEOUT';raise
        rec.update(status='PASS',live_cpu_binding_before_peer_lease_and_stack_proved=True,peer_free_negative_both_directions_proved=True)
    finally:(out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
