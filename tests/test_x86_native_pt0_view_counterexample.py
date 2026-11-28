#!/usr/bin/env python3
"""Reproduce actual PT0 self-view counterexamples; PASS means the gap is observed, not closed."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
import test_x86_native_generation_irq as parent
import test_x86_native_bound_irq as bound
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/x86_native_slab_physical.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_pt0_view_counterexample.S'
COHORT=ROOT/'src/x86_native_page_table_view.hepta'
COHORT_SHA='fe06431f0af785c2f60145f547a4ef5e8067d1f0ba42e37fef9d0aadd9e49928'
COHORT_OBJECT_SHA='eb0d0e961977e0bf40272d9c2f3d2b31fbe2af61930634d5d514d9ba7aeb355b'
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
def fixed_direct_stack_bound(obj):
    """Conservative call-graph bound for this fixed selfhost ELF lowering.
    Reject unknown stack adjustments, indirect calls and cross-function branches.
    This does not prove arbitrary pointer safety or asynchronous stack use.
    """
    asm=run(['objdump','-d','--no-show-raw-insn',obj]).decode()
    ins=[]
    for line in asm.splitlines():
        m=re.match(r'^\s*([0-9a-f]+):\s+(\S+)\s*(.*)$',line)
        if m:ins.append((int(m[1],16),m[2],m[3].strip()))
    assert ins
    starts=[i for i,(_,op,arg) in enumerate(ins) if op in ('push','pushq') and arg=='%rbp']
    assert starts and starts[0]==0
    nodes={}
    for j,i in enumerate(starts):
        end=starts[j+1] if j+1<len(starts) else len(ins)
        a=ins[i][0]
        assert ins[i+1][1] in ('mov','movq') and ins[i+1][2]=='%rsp,%rbp'
        assert ins[i+2][1] in ('sub','subq')
        m=re.fullmatch(r'\$0x([0-9a-f]+),%rsp',ins[i+2][2]);assert m
        frame=int(m[1],16);assert frame>0 and frame%16==0
        calls=[]
        body=ins[i+3:end];addresses={x[0] for x in body}
        assert body and body[-1][1] in ('ret','retq')
        for k,(pc,op,arg) in enumerate(body):
            if op in ('call','callq'):
                t=re.match(r'^(?:0x)?([0-9a-f]+)(?:\s|$)',arg);assert t,(pc,op,arg)
                calls.append(int(t[1],16))
            elif op.startswith('j'):
                t=re.match(r'^(?:0x)?([0-9a-f]+)(?:\s|$)',arg)
                assert t and int(t[1],16) in addresses,(pc,op,arg)
            elif op=='leave':
                assert k+1<len(body) and body[k+1][1] in ('ret','retq')
            elif op in ('ret','retq'):
                assert k and body[k-1][1]=='leave' and not arg
            else:
                assert not op.startswith(('push','pop','enter','iret','sysret','lret')),(pc,op)
                # The compiler probes its newly allocated stack with one read.
                if '%rsp' in arg:
                    assert k==0 and op in ('mov','movq') and arg=='(%rsp),%rax',(pc,op,arg)
                for q in re.finditer(r'-0x([0-9a-f]+)\(%rbp\)',arg):
                    assert 8<=int(q[1],16)<=frame,(pc,op,arg,frame)
                assert '%rbp' not in re.sub(r'-0x[0-9a-f]+\(%rbp\)','',arg),(pc,op,arg)
        nodes[a]=(frame,calls)
    entry=symbol(obj,'f0')
    assert entry in nodes and all(c in nodes for _,cs in nodes.values() for c in cs)
    def bound(a,active):
        assert a not in active
        frame,cs=nodes[a]
        return 16+frame+max((bound(c,active|{a}) for c in cs),default=0)
    return bound(entry,set())
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
    variants=[
        ('pt0-original-bsp',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_BSP_FIRST'],35,'N','native'),
        ('pt0-original-ap',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_AP_FIRST'],35,'N','native'),
        ('pt0-fifth-leaf-bsp',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_BSP_FIRST'],35,'N','five_leaf'),
        ('pt0-fifth-leaf-ap',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_AP_FIRST'],35,'N','five_leaf')]
    mutations={'five_leaf':(b'four:u64 = const() {"value":4}\n  jump scan(root,first,four)',b'four:u64 = const() {"value":5}\n  jump scan(root,first,four)')}
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','compiler_sha256':COMPILER,'compiler_source_sha256':COMPILER_SOURCE,'source_sha256':SOURCE_SHA,'observer_sha256':sha(BOOT.read_bytes()),'objects':{},'cases':[],'general_page_authority_proved':False,'concurrent_mutation_excluded':False,'ist_overflow_fault_proved_in_this_focus':False}
    old_src=(ROOT/'src/x86_native_page_poison.hepta').read_bytes()
    legacy_obj=out/'legacy-poison-stack.o'
    old_bytes,_=compile_pair(compiler,old_src,legacy_obj)
    legacy_bound=fixed_direct_stack_bound(legacy_obj)
    assert legacy_bound==12080 and legacy_bound>8192
    rec['legacy_poison_stack_bound_bytes']=legacy_bound
    rec['legacy_poison_stack_object_sha256']=sha(old_bytes)
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
            stack_bound=fixed_direct_stack_bound(d/'cohort.o')
            assert stack_bound<=7936,(name,stack_bound)
            if mutant=='native':assert sha(rb)==COHORT_OBJECT_SHA
            else:
                assert sha(subject)=='aa5ae3d3755acc767eeed3c9b088d73e2a22b4c2b5d2f313d2b69e7bc3e572d2'
                assert sha(rb)=='f7c636bf937198c6cdbe442d2122799b8bd0def3ec92bc482dbd87046a506b7b'
            reclaim=d/'cohort-link.o';run(['objcopy','--redefine-sym','f0=page_cohort',d/'cohort.o',reclaim]);assert code(reclaim)==rt
            owner=d/'owner-link.o';run(['objcopy','--redefine-sym','f0=page_owner',d/'owner.o',owner]);assert code(owner)==ot
            guard=d/'guard-link.o';run(['objcopy','--redefine-sym','f0=dual_guard',d/'guard.o',guard]);assert code(guard)==gt
            rec['objects'][name]={'direct_stack_bound_bytes':stack_bound,'source_sha256':sha(src),'object_sha256':sha(gb),'text_sha256':sha(gt),'cohort_source_sha256':sha(subject),'cohort_object_sha256':sha(rb),'cohort_text_sha256':sha(rt),'owner_source_sha256':sha(owner_src),'owner_object_sha256':sha(ob),'owner_text_sha256':sha(ot),'entry_object_sha256':sha(raw),'entry_text_sha256':sha(entry_text),'callback_object_sha256':sha(cb)}
            observer=d/'observer.o';guest=d/'guest.elf';image=d/'guest32.elf'
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,BOOT,'-o',observer])
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',parent.LINKER,'-o',guest,observer,out/'callback.o',entry,guard,owner,reclaim])
            run(['objcopy','-O','elf32-i386',guest,image]);actual=code(guest)
            rows=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text'];assert len(rows)==1
            start=int(rows[0][3],16)
            for sym,obj,txt in [('f1',out/'callback.o',ct),('irq_entry',entry,entry_text),('dual_guard',guard,gt),('page_owner',owner,ot),('page_cohort',reclaim,rt)]:
                off=symbol(guest,sym)-start-symbol(obj,sym);assert off>=0 and actual[off:off+len(txt)]==txt
            assert actual==code(image)
            assert symbol(guest,'stack64_top')-symbol(guest,'stack64')==8192
            assert symbol(guest,'ap_stack64_top')-symbol(guest,'ap_stack64')==8192
            assert symbol(guest,'slab')+45056<=2097152
            assert symbol(guest,'pool')==symbol(guest,'slab')+45056
            assert symbol(guest,'pool')+262144<=2097152
            arena=symbol(guest,'pool')
            tables=[symbol(guest,k) for k in ('pml4','pdpt','pd0','pd3','pt0')]
            assert all(not (arena<=t<arena+262144) for t in tables)
            if '-DHIA_TABLE_REMAP' in flags:
                shadow=symbol(guest,'table_shadow');assert shadow>=arena+262144 and shadow+4096<=2097152
            if '-DHIA_ROOT_REMAP' in flags:
                shadow=symbol(guest,'root_shadow');assert shadow>=arena+262144 and shadow+4096<=2097152
            assert OWNER.read_bytes()==owner_src
            for machine in ('pc','q35'):
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'guest_sha256':sha(guest.read_bytes()),'expected_rc':expected,'expected_serial':serial,'status':'FAIL'};rec['cases'].append(row)
                try:
                    p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','2,sockets=1,cores=2,threads=1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],stdin=subprocess.DEVNULL,capture_output=True,timeout=25)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors='replace'));assert (p.returncode,p.stdout)==(expected,serial.encode()),row
                    row['status']='PASS';print(machine,name,p.returncode,p.stdout,flush=True)
                except subprocess.TimeoutExpired:row['status']='TIMEOUT';raise
        assert SOURCE.read_bytes()==src and ENTRY.read_bytes()==esrc and parent.SOURCE.read_bytes()==csrc and sha(compiler.read_bytes())==COMPILER
        rec.update(status='COUNTEREXAMPLE_CONFIRMED', expected_counterexamples=8, pt0_self_view_admission_refused=False, fifth_leaf_scan_refused=False, fixed_direct_stack_bound_limit_bytes=7936, physical_reclamation_proved=False, trusted_pt0_view_required=True)

    finally:(out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
