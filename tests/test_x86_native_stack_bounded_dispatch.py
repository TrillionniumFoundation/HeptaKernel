#!/usr/bin/env python3
"""Fixed non-nested BSP stack-depth qualification, not general IRQ stack authority."""
import argparse, functools, hashlib, json, re, subprocess
from pathlib import Path
from test_x86_native_frame_content import COMPILER, COMPILER_SOURCE, run, sym, text, sha
ROOT=Path(__file__).resolve().parents[1]
# Existing 16376-byte usable stack; 512 additional bytes reserved for
# hardware frame, raw entry, observer call chain and terminal exception.
# Another 512 bytes remain an independently checked bottom canary.
USABLE=16376
OVERHEAD=512
CANARY=512
LIMIT=USABLE-OVERHEAD-CANARY
def bound(obj,export):
    dis=run(['objdump','-d','--no-show-raw-insn',obj],env={'LC_ALL':'C','PATH':'/usr/bin:/bin'}).decode()
    ins=[]
    for line in dis.splitlines():
        m=re.match(r'\s*([0-9a-f]+):\s+(.+)',line)
        if m: ins.append((int(m[1],16),m[2].strip()))
    starts=[i for i in range(len(ins)-2) if ins[i][1]=='push   %rbp' and ins[i+1][1]=='mov    %rsp,%rbp' and re.fullmatch(r'sub\s+\$0x[0-9a-f]+,%rsp',ins[i+2][1])]
    assert starts and starts[0]==0
    funcs={}
    for n,i in enumerate(starts):
        body=ins[i:starts[n+1] if n+1<len(starts) else len(ins)]
        lo=body[0][0]
        alloc=int(re.search(r'\$0x([0-9a-f]+)',body[2][1])[1],16)
        assert alloc%16==0
        calls=[]
        addresses={x[0] for x in body}
        for addr,op in body[3:]:
            if op.startswith('call'):
                m=re.match(r'callq?\s+([0-9a-f]+)\b',op)
                assert m,(obj,hex(addr),op)
                calls.append(int(m[1],16))
            # No dynamic stack adjustments, indirect branches or register writes
            # to RSP/RBP outside the compiler's known prologue/leave.
            assert not re.match(r'(push|pop|enter)\w*\b',op),(obj,hex(addr),op)
            assert not re.search(r',\s*%(rsp|esp|sp|spl|rbp|ebp|bp|bpl)\s*$',op),(obj,hex(addr),op)
            assert not re.match(r'jmpq?\s+\*',op),(obj,hex(addr),op)
            if re.match(r'j[a-z]+\s',op):
                dst=int(re.match(r'j[a-z]+\s+([0-9a-f]+)',op)[1],16)
                assert dst in addresses,(obj,hex(addr),op)
            # All direct frame-relative memory references are within the fixed
            # allocation. RBP/RSP-derived pointers passed to callees are
            # covered by separate caller contract, not a general alias proof.
            for offset in re.findall(r'(-?0x[0-9a-f]+)\(%rbp\)',op):
                assert -alloc<=int(offset,16)<=-8,(obj,hex(addr),op)
            assert not re.search(r'\(%rsp,',op),(obj,hex(addr),op)
            for offset in re.findall(r'(-?0x[0-9a-f]+)?\(%rsp\)',op):
                assert 0<=int(offset or '0',16)<=alloc-8,(obj,hex(addr),op)
        assert body[-1][1] in ('ret','retq','ud2'),(obj,hex(lo),body[-1])
        for j,(_,op) in enumerate(body):
            if op.startswith('ret'):
                assert op in ('ret','retq') and body[j-1][1] in ('leave','leaveq'),(obj,hex(lo),op)
        funcs[lo]=(alloc,calls)
    assert all(c in funcs for _,calls in funcs.values() for c in calls)
    active=set()
    @functools.lru_cache(None)
    def visit(x):
        assert x not in active,'recursive stack graph'
        active.add(x)
        alloc,calls=funcs[x]
        cost,chain=max((visit(c) for c in calls),default=(0,[]),key=lambda p:p[0])
        active.remove(x)
        return alloc+16+cost,[{'address':hex(x),'local_bytes':alloc}]+chain
    cost,chain=visit(sym(obj,export))
    return {'bytes':cost,'chain':chain,'functions':len(funcs)}
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--compiler-dir',type=Path,required=True)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    c=(a.compiler_dir/'compiler-rebuilt-2').resolve()
    assert sha(c.read_bytes())==COMPILER
    assert sha((a.compiler_dir/'candidate.hepta').read_bytes())==COMPILER_SOURCE
    parent=a.parent_output.resolve(); report=json.loads((parent/'report.json').read_bytes())
    assert report['status']=='PASS' and len(report['cases'])==196 and all(x['status']=='PASS' for x in report['cases'])
    out=a.output.resolve();out.mkdir(parents=True)
    source=(ROOT/'src/x86_native_stack_bounded_dispatch.hepta').read_bytes()
    old=(ROOT/'src/x86_native_frame_content.hepta').read_bytes()
    assert source[:source.index(b'fn f37(')]==old[:old.index(b'fn f34(')]
    assert source[source.index(b'fn f36('):source.index(b'fn f0(packed:')]==old[old.index(b'fn f36('):old.index(b'fn f0(packed:')]
    orig=parent/'frame_content.o'
    assert sha(orig.read_bytes())==report['objects']['frame_content']['object_sha256']
    # Parent fails the new budget, rather than claiming its prior green cases prove a bound.
    old_bound=bound(orig,'f0')
    assert old_bound['bytes']>LIMIT
    base_keys=['schedule','restore','irq','handoff','exchange','publisher','owner','dispatch','compensation','guard','block','idle','idle_comp','policy','reserved','reserved_comp']
    inputs=[]
    for k in base_keys:
        raw=parent/(k+'.o'); linked=parent/(k+'-linked.o')
        assert sha(raw.read_bytes())==report['objects'][k]['object_sha256']
        assert text(linked,out/(k+'.text'))==text(raw,out/(k+'-raw.text'))
        assert sha((out/(k+'.text')).read_bytes())==report['objects'][k]['text_sha256']
        inputs.append(linked)
    secondary={}
    for k,exp in [('publisher','hia_publish_ready'),('reserved_comp','hia_reserved_compensation'),('guard','hia_guard_frame_rollback'),('owner','hia_publish_bounded_owner'),('schedule','f4')]:
        info=bound(parent/(k+'-linked.o'),exp)
        assert info['bytes']<=LIMIT,(k,info)
        secondary[exp]=info
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','general_stack_authority_proved':False,'general_smp_proved':False,'scope':'fixed nonnested BSP callback, fixed 16 KiB task stacks','usable':USABLE,'overhead_reserve':OVERHEAD,'canary_bytes':CANARY,'native_limit':LIMIT,'parent_rejected':old_bound,'secondary_callback_bounds':secondary,'objects':{},'cases':[]}
    def change(src,old,new):
        assert src.count(old)==1
        return src.replace(old,new)
    o=b'moved:u64 = call(clean,fo,tab,source,target,fh) {"function":"f16"}'
    b=b'faultstep:u64 = const() {"value":32}\n  faultprior:u64 = int.add.wrap(fo,faultstep)\n  moved:u64 = call(clean,faultprior,tab,source,target,fh) {"function":"f16"}'
    old2=b'rolled:u64 = call(bp,bo,bt,bf,bh,bw) {"function":"f17"}'
    partial=change(change(source,o,b),old2,b'faultgen:u64 = const() {"value":4294967296}\n  faultready:u64 = int.add.wrap(bw,faultgen)\n  rolled:u64 = call(bp,bo,bt,bf,bh,faultready) {"function":"f17"}')
    unknown=change(change(source,o,b),old2,b'faultownerstep:u64 = const() {"value":32}\n  faultrollbackowner:u64 = int.add.wrap(bo,faultownerstep)\n  rolled:u64 = call(bp,faultrollbackowner,bt,bf,bh,bw) {"function":"f17"}')
    noack=change(source,b'_ = x86.mmio.write32(v43,v44)',b'ignored:u32 = x86.mmio.read32(v43)')
    bypass=change(source,b'  valid:bool = bool.and(first,second)',b'  valid:bool = compare.eq(cf,cf)')
    candidates={'bounded':source,'owner-refuse':change(source,o,b),'partial':partial,'unknown':unknown,'noack':noack,'bypass':bypass}
    objects={}
    for key,src in candidates.items():
        raw=out/(key+'.o');data=run([c],input=src,env={'PATH':''})
        assert data==run([c],input=src,env={'PATH':''})
        raw.write_bytes(data)
        assert not run(['nm','-u',raw]).strip()
        assert b'There are no relocations' in run(['readelf','-Wr',raw],env={'LC_ALL':'C','PATH':'/usr/bin:/bin'})
        code=text(raw,out/(key+'.text'));entry=sym(raw,'f0')
        assert code[entry-2:entry]==b'\x0f\x0b'
        info=bound(raw,'f0')
        assert info['bytes']<=LIMIT,(key,info)
        linked=out/(key+'-linked.o');run(['objcopy','--redefine-sym=f0=hia_stack_bounded',raw,linked])
        assert text(linked,out/(key+'-linked.text'))==code
        objects[key]=(linked,code,entry)
        rec['objects'][key]={'source_sha256':sha(src),'object_sha256':sha(data),'text_sha256':sha(code),'bound':info}
    variants=[('short','bounded',[],33,b'P'),('long','bounded',['-DHIA_LONG'],33,b'P'),('owner-refuse','owner-refuse',['-DHIA_DISPATCH_OWNER_REFUSE'],35,b'V'),('partial','partial',['-DHIA_DISPATCH_OWNER_REFUSE','-DHIA_FAILSTOP_PARTIAL','-DHIA_FAILSTOP_TRAP_DELTA=-2'],35,b'Z'),('unknown','unknown',['-DHIA_DISPATCH_OWNER_REFUSE','-DHIA_FAILSTOP_UNKNOWN','-DHIA_FAILSTOP_TRAP_DELTA=-2'],35,b'U'),('noack','noack',['-DHIA_FAILSTOP_EOI','-DHIA_FAILSTOP_TRAP_DELTA=-2'],35,b'E'),('canary','bounded',['-DHIA_STACK_CANARY_FAULT'],35,b'S')]
    for name,offset,value in [('rip',120,0),('cs',128,16),('flags',136,0),('rsp',144,0),('ss',152,24),('bypass',136,0)]:
        variants.append((name,'bypass' if name=='bypass' else 'bounded',[f'-DHIA_FRAME_CORRUPT_OFFSET={offset}',f'-DHIA_FRAME_CORRUPT_VALUE={value}'],35,b'N' if name=='bypass' else b'C'))
    try:
        for name,key,flags,rc,serial in variants:
            case=out/name;case.mkdir()
            obs=case/'observer.o'
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,ROOT/'tests/fixtures/x86_native_stack_bounded_dispatch.S','-o',obs])
            assert not any(op in run(['objdump','-d',obs]).decode().split() for op in ('iret','iretq','iretl'))
            guest=case/'guest.elf';image=case/'guest32.elf';linked,code,entry=objects[key]
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',ROOT/'tests/fixtures/x86_apic_one_shot_timer.ld','-o',guest,obs,*inputs,linked])
            # Bind the 512-byte overhead reserve to this actual independent
            # observer: raw IRQ entry is the hash-pinned inherited 15-GPR
            # save / 40-byte hardware frame / aligned single callback.
            # The observer has 5 pushes, 3 separate one-call alignment
            # helpers, no stack allocation beyond those, and no indirect calls.
            dis=run(['objdump','-d','--no-show-raw-insn',guest],env={'LC_ALL':'C','PATH':'/usr/bin:/bin'}).decode()
            section=dis.split('<irq_dispatch>:',1)[1].split('<task_done>:',1)[0]
            ops=[m.group(1).strip() for m in re.finditer(r'^\s*[0-9a-f]+:\s+(.+)$',section,re.M)]
            stackops=[op for op in ops if re.match(r'(push|pop)\w*\b',op) or re.search(r',\s*%rsp$',op)]
            assert [re.sub(r'\s+',' ',op) for op in stackops]==[
                'push %rbp','push %r12','push %r13','push %r14','push %r15',
                *(['sub $0x8,%rsp','add $0x8,%rsp']*3),
                'pop %r15','pop %r14','pop %r13','pop %r12','pop %rbp'],stackops
            targets=[re.search(r'<([^>]+)>',op)[1] for op in ops if op.startswith('call')]
            assert set(targets)<=set(secondary)|{'hia_stack_bounded','verify_stack_canaries','rollback_compose_args','compensate_mixed'},targets
            assert targets.count('compensate_mixed')<=1 and targets.count('hia_reserved_compensation')==1
            assert 'hia_stack_bounded' in targets
            # No call-chain accumulation across the separately unwound
            # direct dispatch invocations; 160+15+8+40+16+40+8+8+8=303.
            assert OVERHEAD>=303
            run(['objcopy','-O','elf32-i386',guest,image])
            gtext=text(guest,case/'guest.text');assert gtext==text(image,case/'guest32.text')
            sec=[r.split() for r in run(['objdump','-h',guest]).decode().splitlines() if len(r.split())>=6 and r.split()[1]=='.text'];assert len(sec)==1
            lo=sym(guest,'hia_stack_bounded')-int(sec[0][3],16)-entry
            assert gtext[lo:lo+len(code)]==code
            for machine in ('pc','q35'):
                r=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],capture_output=True,timeout=30)
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'expected_rc':rc,'expected_serial':serial.decode(),'returncode':r.returncode,'serial':r.stdout.decode(errors='replace'),'status':'PASS' if (r.returncode,r.stdout)==(rc,serial) else 'FAIL'}
                rec['cases'].append(row);print(json.dumps(row),flush=True)
                assert row['status']=='PASS',row
        rec['status']='PASS'
    finally:
        (out/'report.json').write_text(json.dumps(rec,indent=2)+'\n')
if __name__=='__main__':main()
