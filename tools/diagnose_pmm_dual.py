#!/usr/bin/env python3
"""Temporary bounded native HIA selfhost source-isolation diagnostics.

This produces no accepted kernel component and never weakens test gates.
Retain exact compiler exit statuses, never substitute Python code generation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

original = Path("src/pmm_dual_claim.hepta").read_text()
header = "hia-asm.v1 hepta.hia.program.v8 selfhost_elf\n"
chunks = re.findall(r"(?ms)^fn ([a-zA-Z_][a-zA-Z_0-9]*)\(.*?^end\n", original)
# Gather immutable top-level function blocks while preserving original order.
names = {}
for match in re.finditer(r"(?ms)^fn ([a-zA-Z_][a-zA-Z_0-9]*)\(.*?^end\n", original):
    names[match.group(1)] = match.group(0)
stub = (
    "fn probe(request:readbuf,reply:mutbuf,state:mutbuf) -> (u32) effects() entry(start)\n"
    "block start(request:readbuf,reply:mutbuf,state:mutbuf)\n"
    "  probe_ok:u32 = const() {\"value\":0}\n"
    "  ret(probe_ok)\n"
    "end\n"
)
zone_stub = (
    "fn check_zone(state:mutbuf,offset:u64) -> (u64) effects(read,trap) entry(start)\n"
    "block start(state:mutbuf,offset:u64)\n"
    "  zone_none:u64 = const() {\"value\":8}\n"
    "  ret(zone_none)\n"
    "end\n"
)
commit_stub = (
    "fn commit_zone(reply:mutbuf,state:mutbuf,offset:u64,index:u64) -> (u32) effects(read,write,trap) entry(start)\n"
    "block start(reply:mutbuf,state:mutbuf,offset:u64,index:u64)\n"
    "  commit_ok:u32 = const() {\"value\":0}\n"
    "  ret(commit_ok)\n"
    "end\n"
)
order = list(names)
def assemble(entry, selection, overrides=None):
    overrides = overrides or {}
    return (header + entry + "".join(overrides.get(name, names[name]) for name in order if name in selection)).encode()
variants = {
    "stub-only": header.encode()+stub.encode(),
    "stub-read": assemble(stub, {"read_word"}),
    "stub-write": assemble(stub, {"write_word"}),
    "stub-reply": assemble(stub, {"write_reply","write_word"}),
    "stub-zone": assemble(stub, {"check_zone","read_word"}),
    "stub-commit": assemble(stub, {"commit_zone","read_word","write_word","write_reply"}),
    "stub-all": assemble(stub, set(order)-{"pmm_dual_claim"}),
    "main-stub-zone": assemble(names["pmm_dual_claim"], set(order)-{"pmm_dual_claim"}, {"check_zone":zone_stub}),
    "main-stub-commit": assemble(names["pmm_dual_claim"], set(order)-{"pmm_dual_claim"}, {"commit_zone":commit_stub}),
    "original": original.encode(),
}
compiler = Path(sys.argv[1]).resolve()
rows = []
for name, source in variants.items():
    p = subprocess.run([str(compiler)], input=source, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=12, env={"PATH":""})
    row = {"variant":name, "exit_code":p.returncode, "source_bytes":len(source),
           "source_sha256":hashlib.sha256(source).hexdigest(),
           "object_bytes":len(p.stdout),
           "object_sha256":hashlib.sha256(p.stdout).hexdigest() if p.stdout else None,
           "stderr":p.stderr[:512].decode("utf-8","replace")}
    rows.append(row)
    print(json.dumps(row,sort_keys=True),flush=True)
Path("build").mkdir(exist_ok=True)
Path("build/pmm-dual-source-isolation.json").write_text(json.dumps(rows,indent=2)+"\n")
