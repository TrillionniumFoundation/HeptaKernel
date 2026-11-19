#!/usr/bin/env python3
"""Temporary isolation probe: native selfhost compiler vs prefix CFG subsets."""
from pathlib import Path
import re
import subprocess
import sys

src = Path("src/x86_tlb_plan.hepta").read_text()
first, helper = src.split("\nfn read_request_u64(", 1)
head, body = first.split("\nblock start(", 1)
body = "block start(" + body
blocks = re.findall(r"(?ms)^block ([A-Za-z_][A-Za-z_0-9]*)\([^\n]*\)\n.*?(?=^block |\Z)", body)
raw_blocks = re.findall(r"(?ms)^block [A-Za-z_][A-Za-z_0-9]*\([^\n]*\)\n.*?(?=^block |\Z)", body)
assert len(blocks) == len(raw_blocks) and len(blocks) > 20, len(blocks)
source_by_name = dict(zip(blocks, raw_blocks))
assert len(source_by_name)==len(blocks)
helper="fn read_request_u64("+helper
tiny = '''hia-asm.v1 hepta.hia.program.v8 selfhost_elf
fn tlb_plan(request:readbuf,reply:mutbuf,unused:mutbuf) -> (u32) effects(read,trap) entry(start)
block start(request:readbuf,reply:mutbuf,unused:mutbuf)
  ok:u32 = const() {"value":0}
  ret(ok)
end
'''
for label,data in (("minimal",tiny),("minimal_with_unused_helper",tiny+chr(10)+helper),
                   ("known_good",Path("src/x86_pde_2m.hepta").read_text())):
    p=subprocess.run([sys.argv[1]],input=data.encode("ascii"),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    print("CONTROL",label,"exit",p.returncode,"output_bytes",len(p.stdout),"source_bytes",len(data),flush=True)

simple_call = '''hia-asm.v1 hepta.hia.program.v8 selfhost_elf
fn tlb_plan(request:readbuf,reply:mutbuf,unused:mutbuf) -> (u32) effects(read,trap) entry(start)
block start(request:readbuf,reply:mutbuf,unused:mutbuf)
  off:usize = const() {"value":0}
  word:u64 = call(request,off) {"function":"read_request_u64"}
  narrowed:u32 = int.cast(word) {"mode":"wrap"}
  ret(narrowed)
end
''' + helper
five_calls = '''hia-asm.v1 hepta.hia.program.v8 selfhost_elf
fn tlb_plan(request:readbuf,reply:mutbuf,unused:mutbuf) -> (u32) effects(read,trap) entry(start)
block start(request:readbuf,reply:mutbuf,unused:mutbuf)
  off0:usize = const() {"value":0}
  off8:usize = const() {"value":8}
  off16:usize = const() {"value":16}
  off24:usize = const() {"value":24}
  off32:usize = const() {"value":32}
  a:u64 = call(request,off0) {"function":"read_request_u64"}
  b:u64 = call(request,off8) {"function":"read_request_u64"}
  c:u64 = call(request,off16) {"function":"read_request_u64"}
  d:u64 = call(request,off24) {"function":"read_request_u64"}
  e:u64 = call(request,off32) {"function":"read_request_u64"}
  narrowed:u32 = int.cast(a) {"mode":"wrap"}
  ret(narrowed)
end
''' + helper
for label,data in (("simple_call",simple_call),("five_calls",five_calls)):
    p=subprocess.run([sys.argv[1]],input=data.encode("ascii"),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    print("CONTROL",label,"exit",p.returncode,"out",len(p.stdout),"source_bytes",len(data),flush=True)

for limit in [1, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, len(blocks)]:
    permitted=set(blocks[:limit])
    visited=set()
    todo=["start"]
    while todo:
        name=todo.pop()
        if name in visited: continue
        visited.add(name)
        original=source_by_name[name].rstrip()
        lines=original.splitlines()
        term=lines[-1].strip()
        if term.startswith("branch "):
            targets=re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\(",term)
        elif term.startswith("jump "):
            targets=re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\(",term)
        else: targets=[]
        if set(targets).issubset(permitted):
            todo.extend(targets)
    revised=[]
    for name in blocks:
        if name not in visited: continue
        lines=source_by_name[name].rstrip().splitlines()
        term=lines[-1].strip()
        if term.startswith("branch ") or term.startswith("jump "):
            targets=re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\(",term)
            if not set(targets).issubset(permitted):
                lines[-1]="  probe_status:u32 = const() {\"value\":0}"
                lines.append("  ret(probe_status)")
        revised.append("\n".join(lines))
    candidate=head+"\n"+"\n".join(revised)+"\nend\n"
    if '"function":"read_request_u64"' in candidate:
        candidate += helper
    command = subprocess.run([sys.argv[1]], input=candidate.encode("ascii"),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("PROBE",limit,"reachable",len(visited),"source_bytes",len(candidate),
          "exit",command.returncode,"out",len(command.stdout),
          "stderr",command.stderr[:80].decode("ascii","replace"),flush=True)
