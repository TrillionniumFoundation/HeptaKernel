from pathlib import Path
import argparse,json,subprocess,hashlib,os,re
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--compiler-dir',type=Path,required=True)
parser.add_argument('--parent-output',type=Path,required=True)
parser.add_argument('--bounded-output',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
old=args.parent_output.resolve()
bounded=args.bounded_output.resolve()
fixture=root/'tests/fixtures/x86_apic_one_shot_timer.ld'
c=args.compiler_dir.resolve()
out=args.output.resolve();out.mkdir()
def run(cmd):return subprocess.run([str(x) for x in cmd],check=True,capture_output=True,env={**os.environ,'LC_ALL':'C'}).stdout
def sha(b):return hashlib.sha256(b).hexdigest()
def text(p):
 return run(['objcopy','-O','binary','-j','.text',p,'/dev/stdout'])
def sym(p,n):
 return int(next(x.split()[0] for x in run(['nm',p]).decode().splitlines() if x.split()[-1]==n),16)
r=json.load(open(c/'report.json')); assert r['status']=='PASS'
assert r['compiler_sha256']=='434d32e6e7117796b0540cf635820dca9df10de012c60f7057f47aaffaa2f645'
assert r['source_sha256']=='8a4e5ca4b28cf2c0af4d2199b0ec7a0d32fea25ab6c13710c6c8cd1052a9e2f9'
compiler=c/'compiler-rebuilt-2'
assert sha(compiler.read_bytes())==r['compiler_sha256']
assert sha((c/'candidate.hepta').read_bytes())==r['source_sha256']
source=(root/'src/x86_native_scheduler_stack_entry.hepta').read_bytes()
entry_report=r['irq_stack']
assert len(entry_report['refusals'])==21 and 'missing-atomic' in entry_report['refusals']
assert sha(source)==entry_report['source_sha256']
data=subprocess.run([compiler],input=source,env={'PATH':''},check=True,capture_output=True).stdout
assert data==subprocess.run([compiler],input=source,env={'PATH':''},check=True,capture_output=True).stdout
assert sha(data)==entry_report['elf_sha256']
raw=out/'subject.o';raw.write_bytes(data);code=text(raw);entry=sym(raw,'f0')
assert sha(code)==entry_report['text_sha256']
encoding=bytes.fromhex(entry_report['encoding_hex'])
assert code[entry:entry+len(encoding)]==encoding
assert not run(['nm','-u',raw]).strip()
assert b'There are no relocations' in run(['readelf','-Wr',raw])
base=json.load(open(old/'report.json')); br=json.load(open(bounded/'report.json'))
assert len(base['cases'])==196 and len(br['cases'])==26
keys=['schedule','restore','handoff','exchange','publisher','owner','dispatch','compensation','guard','block','idle','idle_comp','policy','reserved','reserved_comp']
inputs=[]
for k in keys:
 p=old/(k+'-linked.o')
 assert sha((old/(k+'.o')).read_bytes())==base['objects'][k]['object_sha256']
 assert sha(text(p))==base['objects'][k]['text_sha256']
 inputs.append(p)
def linked(label,mutation=None):
 p=out/(label+'.o');p.write_bytes(data)
 if mutation:
  orig,replacement,occ=mutation
  matches=[m.start() for m in re.finditer(re.escape(orig),code)]
  i=matches[occ]; new=code[:i]+replacement+code[i+len(orig):]
  t=out/(label+'.text');t.write_bytes(new)
  run(['objcopy','--update-section','.text='+str(t),p])
  assert text(p)==new
 else: assert text(p)==code
 q=out/(label+'-linked.o')
 run(['objcopy','--redefine-sym=f0=hia_irq_entry',p,q])
 return q
new=linked('native')
no_switch=linked('no-switch',(bytes.fromhex('4c89f4'),b'\x90'*3,0))
no_acquire=linked('no-acquire',(bytes.fromhex('f0490fb1542418'),b'\x90'*7,0))
no_release=linked('no-release',(bytes.fromhex('f0490fb1542418'),b'\x90'*7,1))
def trap(name,macro,offset,callback,busy):
 assert code[entry+offset:entry+offset+2]==b'\x0f\x0b'
 return (name,new,[macro,f'HIA_NATIVE_STACK_TRAP_DELTA={offset}',f'HIA_SCHED_EXPECT_CALLBACK={callback}',f'HIA_SCHED_EXPECT_BUSY={busy}'],35,b'T','bounded')
cases=[('short',new,[],33,b'P','bounded'),('long',new,['HIA_LONG'],33,b'P','bounded'),
trap('bad-bounds','HIA_SCHED_BAD_BOUNDS',0x150,0,0),
trap('alias','HIA_SCHED_ALIAS',0x18c,0,0),
trap('busy','HIA_SCHED_BUSY',0x19f,0,1),
trap('pre-canary','HIA_SCHED_PRE_CANARY',0x1b2,0,1),
trap('post-canary','HIA_SCHED_POST_CANARY',0x1f6,1,1),
trap('bad-selected','HIA_SCHED_BAD_SELECTED',0x23a,1,1),
trap('release-stale','HIA_SCHED_RELEASE_STALE',code.rindex(bytes.fromhex('f0490fb154241874020f0b'))+9-entry,1,2),
('no-switch',no_switch,[],35,b'W','bounded'),('no-acquire',no_acquire,[],35,b'W','bounded'),('no-release',no_release,[],35,b'W','bounded')]
# Corrupt the actual return frame only after the HIA dispatch has succeeded.
# Find the second native restore admission's exact trap instructions.
start=code.index(bytes.fromhex("4c89f84885c075020f0b"),entry)+3
for name,offset,value,pattern,trap_offset in [
    ('rip',120,0,'488b50784885d275020f0b',9),
    ('cs',128,16,'4883b8800000001874020f0b',10),
    ('flags',136,0,'f6c20275020f0b',5),
    ('rsp',144,0,'488b90900000004885d275020f0b',12),
    ('ss',152,24,'4883b8980000001074020f0b',10)]:
    at=code.index(bytes.fromhex(pattern),start)+trap_offset-entry
    case=trap('selected-'+name,'HIA_SCHED_CORRUPT_SELECTED',at,1,1)
    case[2].extend([f'HIA_SCHED_CORRUPT_OFFSET={offset}',f'HIA_SCHED_CORRUPT_VALUE={value}'])
    cases.append(case)
# Rerun the original rollback/fatal/frame fault controls through this stack.
for name,key,flags,serial in [
 ('owner-refuse','owner-refuse',['HIA_DISPATCH_OWNER_REFUSE'],b'V'),
 ('partial','partial',['HIA_DISPATCH_OWNER_REFUSE','HIA_FAILSTOP_PARTIAL','HIA_FAILSTOP_TRAP_DELTA=-2'],b'Z'),
 ('unknown','unknown',['HIA_DISPATCH_OWNER_REFUSE','HIA_FAILSTOP_UNKNOWN','HIA_FAILSTOP_TRAP_DELTA=-2'],b'U'),
 ('noack','noack',['HIA_FAILSTOP_EOI','HIA_FAILSTOP_TRAP_DELTA=-2'],b'E'),
 ('canary','bounded',['HIA_STACK_CANARY_FAULT'],b'S')]:
    cases.append((name,new,flags,35,serial,key))
for name,offset,value in [('rip',120,0),('cs',128,16),('flags',136,0),('rsp',144,0),('ss',152,24),('bypass',136,0)]:
    cases.append(('dispatch-'+name,new,[f'HIA_FRAME_CORRUPT_OFFSET={offset}',f'HIA_FRAME_CORRUPT_VALUE={value}'],35,b'N' if name=='bypass' else b'C','bypass' if name=='bypass' else 'bounded'))
rec={'status':'FAIL','full_linux_acceptance':'HOLD','general_cpu_authority_proved':False,'guard_page_proved':False,'compiler_sha256':r['compiler_sha256'],'compiler_source_sha256':r['source_sha256'],'subject':entry_report,'cases':[]}
try:
 for name,irq,flags,rc,serial,key in cases:
  case=out/name;case.mkdir()
  ob=case/'observer.o';guest=case/'guest.elf';image=case/'guest32.elf'
  run(['cc','-m64','-c','-nostdlib','-fno-pie',*['-D'+f for f in flags],root/'tests/fixtures/x86_native_scheduler_stack.S','-o',ob])
  assert not re.search(r'\biretq?\b',run(['objdump','-d',ob]).decode())
  b=bounded/(key+'-linked.o')
  assert sha(text(b))==br['objects'][key]['text_sha256']
  run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',fixture,'-o',guest,ob,*inputs,irq,b])
  run(['objcopy','-O','elf32-i386',guest,image])
  assert text(guest)==text(image)
  lo,hi=sym(guest,'scheduler_stack'),sym(guest,'scheduler_stack_top')
  assert hi-lo==16384
  for task in range(3):
   a,b=sym(guest,f'task{task}_stack'),sym(guest,f'task{task}_stack_top')
   assert b-a==16384 and (b<=lo or hi<=a)
  descriptor=sym(guest,'irq_dispatch_slot')
  assert descriptor+32<=lo or hi<=descriptor
  # The callback must have no RSP pivot. Check actual linked instructions.
  dis=run(['objdump','-d','--no-show-raw-insn',guest]).decode()
  section=dis.split('<irq_dispatch>:',1)[1].split('<task_done>:',1)[0]
  ops=[m.group(1).strip() for m in re.finditer(r'^\s*[0-9a-f]+:\s+(.+)$',section,re.M)]
  stackops=[re.sub(r'\s+',' ',op) for op in ops if re.match(r'(push|pop)\w*\b',op) or re.search(r',\s*%rsp$',op)]
  assert stackops==[f'cmp $0x{hi-8:x},%rsp','push %rbp','push %r12','push %r13','push %r14','push %r15',*(['sub $0x8,%rsp','add $0x8,%rsp']*3),'pop %r15','pop %r14','pop %r13','pop %r12','pop %rbp'],stackops
  assert br['objects'][key]['bound']['bytes']+512+512<=16384
  # Linked native entry bytes must be exactly the expected object text.
  sec=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text'];assert len(sec)==1
  off=sym(guest,'hia_irq_entry')-int(sec[0][3],16)-entry
  expected=text(irq)
  assert text(guest)[off:off+len(expected)]==expected
  for machine in ('pc','q35'):
   p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64','-smp','1','-m','64M','-accel','tcg','-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio','-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],capture_output=True,timeout=30)
   row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),'expected_rc':rc,'expected_serial':serial.decode(),'rc':p.returncode,'serial':p.stdout.decode(errors='replace'),'status':'PASS' if (p.returncode,p.stdout)==(rc,serial) else 'FAIL'}
   rec['cases'].append(row);print(row,flush=True)
   assert row['status']=='PASS',row
 rec['status']='PASS'
finally:
 (out/'report.json').write_text(json.dumps(rec,indent=2))
