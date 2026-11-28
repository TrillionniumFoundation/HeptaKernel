#!/usr/bin/env python3
"""Actual fixed two-CPU zero-before-publish physical page transfer."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
import test_x86_native_generation_irq as parent
import test_x86_native_bound_irq as bound
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/x86_native_slab_physical.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_audit_shadow.S'
COHORT=ROOT/'src/x86_native_audit_restore.hepta'
COHORT_SHA='1de1e3cb6bcd2f3fb0f8c7885a1de9320c326c974c10aa7ac249a4e42d4aac17'
COHORT_OBJECT_SHA='d085ef26f8efb1ddb7c8afbc373bd08b07ca1e70e94737561a10f1f2826ed2bd'
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
        assert body and body[-1][1] in ('ret','retq','ud2')
        if body[-1][1]=='ud2':
            assert body[-2][1] in ('ret','retq')
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
        ('primary-shadow-bsp',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_BSP_FIRST'],35,'V','native'),
        ('primary-shadow-ap',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_AP_FIRST'],35,'V','native'),
        ('both-shadow-bsp',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_BSP_FIRST','-DHIA_AUDIT_SHADOW'],35,'N','native'),
        ('both-shadow-ap',['-DHIA_TABLE_REMAP','-DHIA_TABLE_PT0','-DHIA_AP_FIRST','-DHIA_AUDIT_SHADOW'],35,'N','native')]
    mutations={'table_view':(b'view_rc:u64 = call(tpt) {"function":"f15"}',b'view_rc:u64 = const() {"value":1}'), 'meta_upper':(b'upper_meta_rc:u64 = call(umpt) {"function":"f4"}',b'upper_meta_rc:u64 = const() {"value":0}'),
               'meta_alias':(b'branch noalias refresh(ms2) denied()',b'jump refresh(ms2)'), 'meta_tlb':(b'_ = x86.tlb.invlpg(meta)',b'_ = x86.fence.mfence()'), 'root':(b'branch root_ok upper_meta(mpt) invalid()',b'jump upper_meta(mpt)'), 'writer':(b'branch tok acquire_lock(tp,tg,to,ti,tr,ta,tl,tf) busy()',b'branch tok acquire_lock(tp,tg,to,ti,tr,ta,tl,tf) bypass(tp,tg,to,ti,tr,ta)\nblock bypass(bp:u64,bg:u64,bo:u64,bi:u64,br:u64,ba:u64)\n  bresult:u64 = call(bp,bg,bo,bi,br,ba) {"function":"f10"}\n  ret(bresult)'), 'upper':(b'branch upok address(uppage,uptable) invalid()',b'jump address(uppage,uptable)'), 'alias':(b'branch v602 slot_valid(v308) invalid()',b'jump slot_valid(v308)'),
               'early':(b'v205:bool = compare.eq(v201,v204)',b'v205:bool = compare.eq(v201,v201)'),
               'remap':(b'x86.atomic.cmpxchg64(v226,v229,v231)',b'x86.atomic.cmpxchg64(v226,v229,v229)'),
               'scrub_cas':(b'x86.atomic.cmpxchg64(v506,v508,v507)',b'x86.atomic.cmpxchg64(v506,v508,v508)'),
               'scrub_skip':(b'v417:u64 = call(v413) {"function":"f2"}',b'v417:u64 = const() {"value":0}'),
               'owner':(b'v220:u64 = bit.or(v219,v401)',b'v220:u64 = bit.or(v219,v211)')}
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
            if mutant not in ('native','restore_fault'):
                if mutant=='owner_gate':
                    old,new=mutations['remap'];assert subject.count(old)==1;subject=subject.replace(old,new)
                    old=b'branch tok acquire_lock(tp,tg,to,ti,tr,ta,tl,tf) busy()'
                    new=b'branch tok acquire_lock(tp,tg,to,ti,tr,ta,tl,tf) bypass_own(tp,tg,to,ti,tr,ta)\nblock bypass_own(bp:u64,bg:u64,bo:u64,bi:u64,br:u64,ba:u64)\n  five:u64 = const() {"value":5}\n  own:bool = compare.ge(bo,five)\n  branch own bypass_do(bp,bg,bo,bi,br,ba) busy()\nblock bypass_do(dp:u64,dg:u64,doo:u64,di:u64,dr:u64,da:u64)\n  rc:u64 = call(dp,dg,doo,di,dr,da) {"function":"f10"}\n  ret(rc)'
                    assert subject.count(old)==1;subject=subject.replace(old,new)
                elif mutant=='upper':
                    old,new=mutations['upper'];assert subject.count(old)==1;subject=subject.replace(old,new)
                    old=b'upper_meta_rc:u64 = call(umpt) {"function":"f4"}'
                    new=b'upper_meta_rc:u64 = const() {"value":0}'
                    assert subject.count(old)==1;subject=subject.replace(old,new)
                elif mutant=='poison':
                    old,new=mutations['remap'];assert subject.count(old)==1;subject=subject.replace(old,new)
                    old=b'branch damaged poison(cl,cf,ch) release_lock(cl,cf,ch,result)'
                    new=b'branch damaged release_lock(cl,cf,ch,result) release_lock(cl,cf,ch,result)'
                    # Keep CFG reachability via an always-false value instead of removing the block.
                    new=b'never:bool = compare.ne(result,result)\n  branch never poison(cl,cf,ch) release_lock(cl,cf,ch,result)'
                    assert subject.count(old)==1;subject=subject.replace(old,new)
                else:
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
            if mutant in ('native','restore_fault'):assert sha(rb)==COHORT_OBJECT_SHA
            else:assert sha(rb)!=COHORT_OBJECT_SHA
            # Fault injection deletes exactly the final native MOV-to-CR3, not its readback.
            # Decode instruction starts with objdump, and bind the trap to the final helper's terminal UD2.
            asm=run(['objdump','-d','--no-show-raw-insn',d/'cohort.o']).decode()
            writes=[int(m[1],16) for m in re.finditer(r'^\s*([0-9a-f]+):\s+mov\s+%rax,%cr3\s*$',asm,re.M)]
            trap=symbol(d/'cohort.o','f0')-2
            assert rt[trap:trap+2]==b'\x0f\x0b'
            assert len(writes)>=2 and writes[-1]<trap and rt[writes[-1]:writes[-1]+6]==b'\x0f\x22\xd8\x0f\x20\xd8'
            if mutant=='restore_fault':
                patch=writes[-1]
                assert rb.count(rt)==1
                i=rb.index(rt)
                rb=rb[:i+patch]+b'\x90'*3+rb[i+patch+3:]
                rt=rt[:patch]+b'\x90'*3+rt[patch+3:]
                (d/'cohort.o').write_bytes(rb)
            reclaim=d/'cohort-link.o'
            run(['objcopy','--redefine-sym','f0=page_cohort_native','--add-symbol',f'audit_restore_trap=.text:0x{trap:x},global',d/'cohort.o',reclaim])
            assert code(reclaim)==rt
            owner=d/'owner-link.o';run(['objcopy','--redefine-sym','f0=page_owner',d/'owner.o',owner]);assert code(owner)==ot
            guard=d/'guard-link.o';run(['objcopy','--redefine-sym','f0=dual_guard',d/'guard.o',guard]);assert code(guard)==gt
            rec['objects'][name]={'direct_stack_bound_bytes':stack_bound,'source_sha256':sha(src),'object_sha256':sha(gb),'text_sha256':sha(gt),'cohort_source_sha256':sha(subject),'cohort_object_sha256':sha(rb),'cohort_text_sha256':sha(rt),'owner_source_sha256':sha(owner_src),'owner_object_sha256':sha(ob),'owner_text_sha256':sha(ot),'entry_object_sha256':sha(raw),'entry_text_sha256':sha(entry_text),'callback_object_sha256':sha(cb)}
            observer=d/'observer.o';guest=d/'guest.elf';image=d/'guest32.elf'
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,BOOT,'-o',observer])
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',parent.LINKER,'-o',guest,observer,out/'callback.o',entry,guard,owner,reclaim])
            run(['objcopy','-O','elf32-i386',guest,image]);actual=code(guest)
            rows=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text'];assert len(rows)==1
            start=int(rows[0][3],16)
            for sym,obj,txt in [('f1',out/'callback.o',ct),('irq_entry',entry,entry_text),('dual_guard',guard,gt),('page_owner',owner,ot),('page_cohort_native',reclaim,rt)]:
                off=symbol(guest,sym)-start-symbol(obj,sym);assert off>=0 and actual[off:off+len(txt)]==txt
            assert actual==code(image)
            assert symbol(guest,'stack64_top')-symbol(guest,'stack64')==8192
            assert symbol(guest,'ap_stack64_top')-symbol(guest,'ap_stack64')==8192
            assert symbol(guest,'slab')+45056<=2097152
            assert symbol(guest,'pool')==symbol(guest,'slab')+45056
            assert symbol(guest,'pool')+262144<=2097152
            arena=symbol(guest,'pool')
            tables=[symbol(guest,k) for k in ('pml4','pdpt','pd0','pd3','pt0','audit_pml4','audit_pdpt','audit_pd0')]
            assert tables==list(range(tables[0],tables[0]+32768,4096))
            assert tables[-1]+4096<=2097152
            assert all(not (arena<=t<arena+262144) for t in tables)
            if '-DHIA_TABLE_REMAP' in flags:
                shadow=symbol(guest,'table_shadow');assert shadow>=arena+262144 and shadow+4096<=2097152
            if '-DHIA_ROOT_REMAP' in flags:
                shadow=symbol(guest,'root_shadow');assert shadow>=arena+262144 and shadow+4096<=2097152
            if '-DHIA_AUDIT_SHADOW' in flags:
                audit_pt=symbol(guest,'audit_pt_shadow')
                assert audit_pt>=arena+262144 and audit_pt+4096<=2097152
                assert audit_pt not in tables and audit_pt!=shadow
            assert OWNER.read_bytes()==owner_src
            for machine in ('pc','q35'):
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'guest_sha256':sha(guest.read_bytes()),'expected_rc':expected,'expected_serial':serial,'status':'FAIL'};rec['cases'].append(row)
                try:
                    p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','2,sockets=1,cores=2,threads=1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],stdin=subprocess.DEVNULL,capture_output=True,timeout=25)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors='replace'));assert (p.returncode,p.stdout)==(expected,serial.encode()),row
                    row['status']='PASS';print(machine,name,p.returncode,p.stdout,flush=True)
                except subprocess.TimeoutExpired:row['status']='TIMEOUT';raise
        assert SOURCE.read_bytes()==src and ENTRY.read_bytes()==esrc and parent.SOURCE.read_bytes()==csrc and sha(compiler.read_bytes())==COMPILER
        rec.update(status='COUNTEREXAMPLE_CONFIRMED',fixed_boot_audit_root_switch=True,original_cr3_readback=True,actual_audit_leaf_accessed=True,primary_only_pt0_redirection_refused=True,both_views_pt0_redirection_accepted=True,actual_lease_mutation=True,boot_sealed_audit_root_required=True,if_zero_caller_required=True,arbitrary_root_authority_proved=False,concurrent_mutation_excluded=False,physical_reclamation_proved=False,original_post_iret_stale_control_met=False)

    finally:(out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
