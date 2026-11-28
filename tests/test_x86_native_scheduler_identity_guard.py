"""Actual guarded scheduler stack and IST fault observation; fixed BSP only."""
from pathlib import Path
import argparse, hashlib, json, os, re, subprocess

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
for name in ('compiler-dir', 'parent-output', 'bounded-output', 'scheduler-output', 'output'):
    parser.add_argument('--'+name, type=Path, required=True)
args=parser.parse_args()
c, old, bounded, scheduler, out = (getattr(args,n).resolve() for n in ('compiler_dir','parent_output','bounded_output','scheduler_output','output'))
out.mkdir()
def run(cmd):
    return subprocess.run([str(x) for x in cmd], check=True, capture_output=True, env={**os.environ,'LC_ALL':'C'}).stdout
def sha(b):
    return hashlib.sha256(b).hexdigest()
def text(p):
    return run(['objcopy','-O','binary','-j','.text',p,'/dev/stdout'])
def sym(p,n):
    return int(next(x.split()[0] for x in run(['nm',p]).decode().splitlines() if x.split()[-1]==n),16)
def read(p):
    return json.loads(p.read_text())
cr=read(c/'report.json')
assert cr['status']=='PASS' and cr['compiler_sha256']=='434d32e6e7117796b0540cf635820dca9df10de012c60f7057f47aaffaa2f645'
assert cr['source_sha256']=='8a4e5ca4b28cf2c0af4d2199b0ec7a0d32fea25ab6c13710c6c8cd1052a9e2f9'
compiler=c/'compiler-rebuilt-2'
assert sha(compiler.read_bytes())==cr['compiler_sha256']
assert sha((c/'candidate.hepta').read_bytes())==cr['source_sha256']
src=root/'src/x86_native_scheduler_identity_guard.hepta'
source=src.read_bytes()
assert sha(source)=='75880bf0e5ee7260af240794fa3da08c08613f2fccba664e7163bb51a6437df4'
data=subprocess.run([compiler],input=source,env={'PATH':''},check=True,capture_output=True).stdout
assert data==subprocess.run([compiler],input=source,env={'PATH':''},check=True,capture_output=True).stdout
assert sha(data)=='707b4e5c077c599cae7581bc87532c56f3ac749731820ddb4dd48a41c0bcbbda'
raw=out/'guard.o';raw.write_bytes(data);code=text(raw)
assert sha(code)=='ba25fcefe112673fafcea16384ffb414bcd7424c230d9677b1a661f82cea5205'
assert not run(['nm','-u',raw]).strip()
assert b'There are no relocations' in run(['readelf','-Wr',raw])
# Independently identify the two distinct native CAS operations and invalidation.
cas=bytes.fromhex('f0480fb10a')
positions=[m.start() for m in re.finditer(re.escape(cas),code)]
assert positions==[0xa0,0x3c9,0xef6]
inv=bytes.fromhex('0f0138')
assert [m.start() for m in re.finditer(re.escape(inv),code)]==[0x433]
assert code[0x429:0x42c]==bytes.fromhex('0faef0')
for off,op in [(0x1296,'0f20d8'),(0x12a0,'0f20e0'),(0x12aa,'0f20c0')]:
    assert code[off:off+3]==bytes.fromhex(op)
def linked(label,offset=None,op=None):
    p=out/(label+'-linked.o')
    if offset is None:
        run(['objcopy','--redefine-sym=f0=hia_scheduler_guard',raw,p])
        assert text(p)==code
    else:
        assert code[offset:offset+len(op)]==op
        t=out/(label+'.text')
        t.write_bytes(code[:offset]+b'\x90'*len(op)+code[offset+len(op):])
        run(['objcopy','--update-section','.text='+str(t),'--redefine-sym=f0=hia_scheduler_guard',raw,p])
        assert text(p)==t.read_bytes()
    return p
native=linked('native')
no_parent=linked('no-parent',positions[0],cas)
no_leaf=linked('no-leaf',positions[1],cas)
no_scan=linked('no-scan',positions[2],cas)
no_invlpg=linked('no-invlpg',0x433,inv)
base,br,sr=(read(p/'report.json') for p in (old,bounded,scheduler))
assert all(r['status']=='PASS' for r in (base,br,sr))
assert [len(r['cases']) for r in (base,br,sr)]==[196,26,56]
assert sr['compiler_sha256']==cr['compiler_sha256'] and sr['subject']==cr['irq_stack']
assert sha((scheduler/'subject.o').read_bytes())==sr['subject']['elf_sha256']
irq=scheduler/'native-linked.o'
assert sha(text(irq))==sr['subject']['text_sha256']
keys=['schedule','restore','handoff','exchange','publisher','owner','dispatch','compensation','guard','block','idle','idle_comp','policy','reserved','reserved_comp']
inputs=[]
for k in keys:
    p=old/(k+'-linked.o')
    assert sha((old/(k+'.o')).read_bytes())==base['objects'][k]['object_sha256']
    assert sha(text(p))==base['objects'][k]['text_sha256']
    inputs.append(p)
b=bounded/'bounded-linked.o'
assert sha(text(b))==br['objects']['bounded']['text_sha256']
cases=[
    ('short',native,[],33,b'P'),
    ('long',native,['HIA_LONG'],33,b'P'),
    ('overflow',native,['HIA_GUARD_OVERFLOW'],35,b'Q'),
    ('mapped',native,['HIA_GUARD_OVERFLOW','HIA_GUARD_MAPPED'],35,b'M'),
    ('no-parent',no_parent,[],35,b'J'),
    ('no-leaf',no_leaf,[],35,b'J'),
    ('no-scan',no_scan,[],35,b'J'),
    ('no-invlpg',no_invlpg,['HIA_GUARD_OVERFLOW'],35,b'M')]
fixture=root/'tests/fixtures/x86_apic_one_shot_timer.ld'
rec={'status':'FAIL','full_linux_acceptance':'HOLD','general_page_authority_proved':False,
     'fixed_identity_guard_page_proved':False,'fixed_low_leaf_alias_refusal_proved':False,'source_sha256':sha(source),
     'object_sha256':sha(data),'text_sha256':sha(code),'compiler_sha256':cr['compiler_sha256'],
     'inherited_cases':[196,26,56],'cases':[]}
try:
    for name,g,flags,rc,serial in cases:
        case=out/name;case.mkdir()
        ob=case/'observer.o';guest=case/'guest.elf';image=case/'guest32.elf'
        run(['cc','-m64','-c','-nostdlib','-fno-pie',*['-D'+f for f in flags],
             root/'tests/fixtures/x86_native_scheduler_identity_guard.S','-o',ob])
        assert not re.search(r'\biretq?\b',run(['objdump','-d',ob]).decode())
        run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',fixture,
             '-o',guest,ob,*inputs,irq,b,g])
        run(['objcopy','-O','elf32-i386',guest,image])
        assert text(guest)==text(image)
        guard,lo,hi,fl,fh=(sym(guest,n) for n in ('scheduler_guard','scheduler_stack','scheduler_stack_top','fault_stack','fault_stack_top'))
        assert guard%4096==lo%4096==fl%4096==0
        assert guard+4096==lo and hi-lo==16384 and fh-fl==4096 and hi<=fl and fh<0x200000
        for i in range(3):
            tlo,thi=(sym(guest,f'task{i}_stack'+suffix) for suffix in ('','_top'))
            assert thi-tlo==16384 and (thi<=guard or fh<=tlo)
        pages=[sym(guest,n) for n in ('pml4','pdpt','pd0','pt0')]
        assert len(set(pages))==4 and all(x%4096==0 and x+4096<=guard for x in pages)
        sec=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text']
        assert len(sec)==1
        # Verify linked native guard and IRQ bytes, including each deliberate mutation.
        linked_text=text(guest)
        for path,symbol in [(g,'hia_scheduler_guard'),(irq,'hia_irq_entry')]:
            off=sym(guest,symbol)-int(sec[0][3],16)-sym(path,symbol)
            expected=text(path)
            assert linked_text[off:off+len(expected)]==expected
        for machine in ('pc','q35'):
            p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','1','-m','64M',
               '-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown',
               '-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global',
               'isa-debugcon.iobase=0xe9','-kernel',str(image)],capture_output=True,timeout=30)
            row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'expected_rc':rc,
                 'expected_serial':serial.decode(),'rc':p.returncode,'serial':p.stdout.decode(errors='replace'),
                 'status':'PASS' if (p.returncode,p.stdout)==(rc,serial) else 'FAIL'}
            rec['cases'].append(row);print(row,flush=True)
            assert row['status']=='PASS',row
    rec['status']='PASS'
    rec['fixed_identity_guard_page_proved']=True
    rec['fixed_low_leaf_alias_refusal_proved']=True
finally:
    (out/'report.json').write_text(json.dumps(rec,indent=2))
