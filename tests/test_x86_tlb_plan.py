#!/usr/bin/env python3
"""Independent oracle for a genuine selfhost-compiled, single-page HIA TLB plan checker."""
import argparse
import ctypes
import hashlib
import json
import random
import struct
from pathlib import Path

MASK = (1 << 64) - 1
ROOT = 0x200000
VA = 0x400000
F = 15

def pack(root=ROOT, owner=ROOT, va=VA, flags=F, rows=None):
    if rows is None:
        rows = [(1,0,0,0,0),(2,VA,0,0,0x8000000000200085),
                (3,VA,0,0,0),(4,0,0,0,0)]
    return struct.pack("<5Q",root,owner,va,flags,len(rows)) + b"".join(
        struct.pack("<5Q", *row) for row in rows)

def oracle(data):
    if len(data) < 40:
        return 1
    root,owner,va,flags,n = struct.unpack_from("<5Q",data)
    if not 1 <= n <= 64 or len(data) != 40+40*n:
        return 1
    if root == 0 or root & 4095 or root >= 1<<52 or root != owner or flags != 15:
        return 2
    sign=(va>>47)&1
    if va & 4095 or (va>>48) != (65535 if sign else 0):
        return 3
    masked=pending=seen=False
    last=0
    writes=pairs=0
    for op,page,old,observed,new in struct.iter_unpack("<5Q",data[40:]):
        if op == 1:
            if masked or (page,old,observed,new)!=(0,0,0,0): return 4
            masked=True
        elif op == 2:
            if (not masked or pending or page != va or observed != old or
                    new == old or (seen and old != last)): return 4
            seen=True
            last=new
            pending=True
            writes+=1
        elif op == 3:
            if (not masked or not pending or page != va or
                    (old,observed,new)!=(0,0,0)): return 4
            pending=False
        elif op == 4:
            if not masked or pending or (page,old,observed,new)!=(0,0,0,0):
                return 4
            masked=False
            pairs+=1
        else: return 4
    if masked or pending or writes == 0 or pairs == 0:
        return 4
    return 0

def campaign(path):
    func = ctypes.CDLL(str(Path(path).resolve())).f0
    func.argtypes = [ctypes.c_void_p,ctypes.c_uint64]*3
    func.restype = ctypes.c_uint32
    rng = random.Random(0x77B2AC11)
    rows = [(1,0,0,0,0),(2,VA,0,0,0x200085),
            (3,VA,0,0,0),(2,VA,0x200085,0x200085,0x8000000000200085),
            (3,VA,0,0,0),(4,0,0,0,0)]
    cases=[pack(),pack(rows=rows),
           pack(rows=[(1,0,0,0,0),(2,VA,0,0,1),(3,VA,0,0,0),
                      (4,0,0,0,0),(1,0,0,0,0),(2,VA,1,1,2),
                      (3,VA,0,0,0),(4,0,0,0,0)])]
    for i in range(640):
        root=rng.choice([ROOT,0,1,0xFFFFFFFFFFFFF000,ROOT+1])
        owner=rng.choice([root,ROOT,0])
        va=rng.choice([VA,0,0xffff800000004000,0x800000000000,VA+1,VA+4096])
        flags=rng.choice([15,15,15,0,14,31])
        operations=[tuple(r) for r in rows]
        for _ in range(rng.randrange(1,5)):
            k=rng.randrange(len(operations))
            rr=list(operations[k])
            rr[rng.randrange(5)]=rng.choice([0,1,2,3,4,VA,VA+4096,0x200085,MASK])
            operations[k]=tuple(rr)
        if rng.randrange(9)==0: operations=operations[:rng.randrange(1,len(operations))]
        cases.append(pack(root,owner,va,flags,operations))
    # Genuine valid single-page plans under different canonical VAs and owned
    # roots, including repeated updates whose old word is the prior candidate.
    # These positives prevent an always-refuse implementation from passing.
    for i in range(160):
        page = rng.choice([VA, 0, 4096, 0xffff800000004000, 0xfffffffffffff000])
        root = rng.randrange(1, 1 << 40) << 12
        old, candidate = rng.getrandbits(64), rng.getrandbits(64)
        if old == candidate:
            candidate ^= 1
        plan = [(1,0,0,0,0),(2,page,old,old,candidate),(3,page,0,0,0)]
        if i % 3 == 0:
            successor = candidate ^ (1 << rng.randrange(64))
            plan.extend([(2,page,candidate,candidate,successor),(3,page,0,0,0)])
            candidate = successor
        plan.append((4,0,0,0,0))
        if i % 7 == 0:
            successor = candidate ^ (1 << rng.randrange(64))
            plan.extend([(1,0,0,0,0),(2,page,candidate,candidate,successor),
                         (3,page,0,0,0),(4,0,0,0,0)])
        raw = pack(root,root,page,F,plan)
        assert oracle(raw) == 0, ("invalid positive fixture",i)
        cases.append(raw)
    cases.extend([b"",b"\0"*39,pack()+b"\0", pack(rows=[]),
                  pack(root=0), pack(va=1<<48),pack(flags=0),
                  pack(rows=rows[:3]),pack(rows=rows[:4]),
                  pack(rows=rows[:5]),
                  pack(rows=[(1,0,0,0,0),(2,VA,0,0,1),
                             (3,VA,0,0,0),(2,VA,0,0,2),
                             (3,VA,0,0,0),(4,0,0,0,0)]),
                  pack(rows=[(1,0,0,0,0),(2,VA,0,0,1),
                             (3,VA,0,0,0),(2,VA,1,0,2),
                             (3,VA,0,0,0),(4,0,0,0,0)])])
    passed=denied=0
    for raw in cases:
        input_buf=ctypes.create_string_buffer(b"\xa1"*32+raw+b"\xa1"*32)
        reply=ctypes.create_string_buffer(b"\xb2"*64)
        workspace=ctypes.create_string_buffer(b"\xc3"*64)
        before=(bytes(input_buf),bytes(reply),bytes(workspace))
        got=func(ctypes.addressof(input_buf)+32,len(raw),
                 ctypes.addressof(reply),64,
                 ctypes.addressof(workspace),64)
        want=oracle(raw)
        assert got == want, (got,want,raw.hex()[:200])
        assert (bytes(input_buf),bytes(reply),bytes(workspace)) == before, "hidden mutation"
        passed+=got==0
        denied+=got!=0
    assert passed>=160 and denied>=100, (passed,denied)
    return (len(cases),passed,denied)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("library")
    parser.add_argument("--expect-unsafe", action="store_true")
    args=parser.parse_args()
    if args.expect_unsafe:
        try: campaign(args.library)
        except AssertionError as error:
            print("dishonest native HIA TLB planner rejected:",str(error)[:100])
            return
        raise SystemExit("dishonest native HIA TLB planner falsely passed")
    count,passed,denied=campaign(args.library)
    report = {"schema": "heptakernel.hia-x86-tlb-plan.v1", "status": "PASS",
              "cases":count,"accepted":passed,"refused":denied,
              "source_sha256":hashlib.sha256(Path("src/x86_tlb_plan.hepta").read_bytes()).hexdigest(),
              "object_sha256":hashlib.sha256(Path("build/x86-tlb-plan.o").read_bytes()).hexdigest(),
              "library_sha256":hashlib.sha256(Path(args.library).read_bytes()).hexdigest(),
              "privileged_operations_executed":False,"cpu_state_authenticated":False,
              "single_cpu_only":True,"linux_full_acceptance":"HOLD"}
    Path("build/x86-tlb-plan-report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("real HIA TLB effect admission:",report)

if __name__ == "__main__":
    main()
