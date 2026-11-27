#!/usr/bin/env python3
"""Two actual xAPIC CPUs admit their own fixed dense descriptor; not general CPU authority."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/x86_native_percpu_descriptor.hepta'
BOOT=ROOT/'tests/fixtures/x86_native_percpu_descriptor.S'
LINKER=ROOT/'tests/fixtures/x86_native_percpu_descriptor.ld'
COMPILER='434d32e6e7117796b0540cf635820dca9df10de012c60f7057f47aaffaa2f645'
COMPILER_SOURCE='8a4e5ca4b28cf2c0af4d2199b0ec7a0d32fea25ab6c13710c6c8cd1052a9e2f9'
SOURCE_SHA='905bbb8e5dde296639e5cacdcc7486c55712d078677f8373c966bbf66ce5f956'
OBJECT_SHA='523e2e149fdf14356280dc75568b2555ab4d3679c884e69e0b6e6a36e49fe558'
def sha(b): return hashlib.sha256(b).hexdigest()
def run(argv,**kw):
    kw.setdefault('env',{**os.environ,'LC_ALL':'C'})
    return subprocess.run([str(x) for x in argv],check=True,capture_output=True,timeout=60,**kw).stdout
def code(p): return run(['objcopy','-O','binary','-j','.text',p,'/dev/stdout'])
def symbol(p,name):
    rows=[x.split() for x in run(['nm','-n',p]).decode().splitlines() if x.split()[-1:]==[name]]
    assert len(rows)==1,(name,rows)
    return int(rows[0][0],16)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--compiler-dir',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    c=a.compiler_dir.resolve(); out=a.output.resolve(); out.mkdir()
    compiler=c/'compiler-rebuilt-2'
    report=json.loads((c/'report.json').read_text())
    assert report['status']=='PASS' and report['compiler_sha256']==COMPILER==sha(compiler.read_bytes())
    assert report['source_sha256']==COMPILER_SOURCE==sha((c/'candidate.hepta').read_bytes())
    source=SOURCE.read_bytes()
    assert sha(source)==SOURCE_SHA
    mutations=[
        ('wrong-live-id',b'actual:u32 = bit.and(raw,idmask)',b'actual:u32 = const() {"value":0}',b'I'),
        ('ignore-gs',b'correct:bool = compare.eq(gs,desc)',b'correct:bool = compare.eq(desc,desc)',b'G'),
        ('ignore-callback',b'cbok:bool = compare.eq(gotcb,cc)',b'cbok:bool = compare.eq(cc,cc)',b'B'),
        ('ignore-low',b'lowok:bool = compare.eq(gotlow,ll)',b'lowok:bool = compare.eq(ll,ll)',b'L'),
        ('ignore-top',b'topok:bool = compare.eq(gottop,tt)',b'topok:bool = compare.eq(tt,tt)',b'T'),
        ('ignore-lease',b'leaseok:bool = compare.eq(gotlease,free)',b'leaseok:bool = compare.eq(free,free)',b'E'),
        ('ignore-extent',b'exact:bool = compare.eq(finish,le)',b'exact:bool = compare.eq(finish,finish)',b'R'),
    ]
    rec={'status':'FAIL','full_linux_acceptance':'HOLD','compiler_sha256':COMPILER,
         'compiler_source_sha256':COMPILER_SOURCE,'source_sha256':SOURCE_SHA,
         'observer_sha256':sha(BOOT.read_bytes()),'linker_sha256':sha(LINKER.read_bytes()),
         'general_cpu_authority_proved':False,'general_page_authority_proved':False,
         'general_smp_proved':False,'actual_scheduler_switch_proved':False,
         'fixed_dense_apic_descriptor_admission_proved':False,'objects':{},'cases':[]}
    variants=[('native',source,33,b'P')]
    for name,old,new,serial in mutations:
        assert source.count(old)==1
        variants.append((name,source.replace(old,new),35,serial))
    try:
        for name,src,expected,serial in variants:
            d=out/name; d.mkdir()
            obj=d/'native.o'
            binary=run([compiler],input=src,env={'PATH':''})
            assert binary==run([compiler],input=src,env={'PATH':''})
            obj.write_bytes(binary)
            assert not run(['nm','-u',obj]).strip()
            assert b'There are no relocations' in run(['readelf','-Wr',obj])
            native=code(obj)
            if name=='native':
                assert sha(binary)==OBJECT_SHA
                assert sha(native)=='378781c9a93401435750b0509f47848cfc7d360dc864d1ddc6576cd7506a2a55'
                assert native.count(bytes.fromhex('f0480fb10a'))==4
            else: assert sha(binary)!=OBJECT_SHA
            rec['objects'][name]={'source_sha256':sha(src),'object_sha256':sha(binary),'text_sha256':sha(native)}
            observer=d/'observer.o'; guest=d/'guest.elf'; image=d/'guest32.elf'
            flags=[] if name=='native' else ['-DHIA_SERIAL_NEGATIVE']
            run(['cc','-m64','-c','-nostdlib','-fno-pie',*flags,BOOT,'-o',observer])
            run(['ld','-nostdlib','-z','noexecstack','-z','max-page-size=0x1000','-T',LINKER,'-o',guest,observer,obj])
            run(['objcopy','-O','elf32-i386',guest,image])
            rows=[x.split() for x in run(['objdump','-h',guest]).decode().splitlines() if len(x.split())>=6 and x.split()[1]=='.text']
            assert len(rows)==1
            off=symbol(guest,'f0')-int(rows[0][3],16)-symbol(obj,'f0')
            actual=code(guest)
            assert off>=0 and actual==code(image) and actual[off:off+len(native)]==native
            for machine in ('pc','q35'):
                row={'case':name,'machine':machine,'image_sha256':sha(image.read_bytes()),
                     'guest_sha256':sha(guest.read_bytes()),'expected_rc':expected,
                     'expected_serial':serial.decode(),'status':'FAIL'}
                rec['cases'].append(row)
                try:
                    p=subprocess.run(['qemu-system-x86_64','-machine',machine,'-cpu','qemu64',
                        '-smp','2,sockets=1,cores=2,threads=1','-m','64M','-accel','tcg',
                        '-display','none','-serial','none','-monitor','none','-no-reboot','-no-shutdown',
                        '-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-debugcon','stdio',
                        '-global','isa-debugcon.iobase=0xe9','-kernel',str(image)],
                        capture_output=True,timeout=25)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors='replace'))
                    assert (p.returncode,p.stdout)==(expected,serial),row
                    row['status']='PASS'
                    print(machine,name,p.returncode,p.stdout,flush=True)
                except subprocess.TimeoutExpired:
                    row['status']='TIMEOUT'
                    raise
        assert SOURCE.read_bytes()==source and sha(compiler.read_bytes())==COMPILER
        rec.update(status='PASS',fixed_dense_apic_descriptor_admission_proved=True,
                   exact_fixture_vcpus=2,shared_start_two_cpu_checks=True)
    finally:
        (out/'report.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
if __name__=='__main__': main()
