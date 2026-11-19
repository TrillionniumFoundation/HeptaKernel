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
    candidate=head+"\n"+"\n".join(revised)+"\nend\n"+helper
    # Keep the helper reachable, otherwise the pinned native compiler may
    # reject an unused second function before diagnosing the candidate CFG.
    signature="block start(request:readbuf,reply:mutbuf,unused:mutbuf)\n"
    inject='  probe_offset:usize = const() {"value":0}\n  probe_value:u64 = call(request,probe_offset) {"function":"read_request_u64"}\n'
    candidate=candidate.replace(signature,signature+inject,1)
    command = subprocess.run([sys.argv[1]], input=candidate.encode("ascii"),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("PROBE",limit,"reachable",len(visited),"source_bytes",len(candidate),
          "exit",command.returncode,"out",len(command.stdout),
          "stderr",command.stderr[:80].decode("ascii","replace"),flush=True)

# Temporary controls to distinguish the source grammar, first-entry ABI,
# unused helper acceptance and target effect spelling.
print("PROBE CONTROL MATRIX", flush=True)
for name, first_name, effect, keep_helper, include_load in [
    ("minimal-read", "tlb_plan", "read,trap", False, False),
    ("minimal-read-helper", "tlb_plan", "read,trap", True, False),
    ("minimal-write-helper", "tlb_plan", "read,write,trap", True, False),
    ("minimal-f0-helper", "f0", "read,trap", True, False),
    ("minimal-load", "tlb_plan", "read,trap", False, True),
    ("minimal-load-helper", "tlb_plan", "read,trap", True, True),
]:
    body = "  sample:usize = buffer.len(request)\n" if include_load else ""
    sample = (
       "hia-asm.v1 hepta.hia.program.v8 selfhost_elf\n"
       f"fn {first_name}(request:readbuf,reply:mutbuf,unused:mutbuf) -> (u32) effects({effect}) entry(start)\n"
       "block start(request:readbuf,reply:mutbuf,unused:mutbuf)\n"
       + body + "  sample_status:u32 = const() {\"value\":0}\n  ret(sample_status)\nend\n"
       + (helper if keep_helper else "")
    )
    result = subprocess.run([sys.argv[1]], input=sample.encode("ascii"),
         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("PROBE CONTROL",name,"exit",result.returncode,
          "source_bytes",len(sample),"out",len(result.stdout),
          "stderr",result.stderr[:64].decode("ascii","replace"),flush=True)

call_src = (
 "hia-asm.v1 hepta.hia.program.v8 selfhost_elf\n"
 "fn tlb_plan(request:readbuf,reply:mutbuf,unused:mutbuf) -> (u32) effects(read,trap) entry(start)\n"
 "block start(request:readbuf,reply:mutbuf,unused:mutbuf)\n"
 '  pos:usize = const() {"value":0}\n'
 '  got:u64 = call(request,pos) {"function":"read_request_u64"}\n'
 '  done:u32 = const() {"value":0}\n'
 "  ret(done)\nend\n" + helper
)
result = subprocess.run([sys.argv[1]],input=call_src.encode("ascii"),
 stdout=subprocess.PIPE,stderr=subprocess.PIPE)
print("PROBE CONTROL minimal-call-helper","exit",result.returncode,
 "source_bytes",len(call_src),"out",len(result.stdout),flush=True)
