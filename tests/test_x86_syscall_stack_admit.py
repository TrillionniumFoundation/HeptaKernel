#!/usr/bin/env python3
"""Independent oracle for narrow HIA-native SYSCALL stack preflight.

Does not authenticate physical ownership or implement a privilege switch.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import random
import subprocess
import tempfile
from pathlib import Path

MAX64 = (1 << 64) - 1
SEED = 0x57ACAC14

def oracle(user: int, kernel: int, tss: int) -> int:
    if not 4096 <= user < (1 << 47):
        return 1
    if not 4096 <= kernel < 0x400000 or kernel & 15:
        return 2
    return 0 if tss == kernel else 3

def code_hash(obj: Path, lib: Path) -> str:
    results = []
    with tempfile.TemporaryDirectory() as d:
        for i, p in enumerate((obj, lib)):
            raw = Path(d) / str(i)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(p.resolve()), str(raw)], check=True,
                           capture_output=True, timeout=20)
            b = raw.read_bytes()
            assert b, "empty native HIA .text"
            results.append(hashlib.sha256(b).hexdigest())
    assert results[0] == results[1], "linked .text changed"
    return results[0]

def check(lib: Path, obj: Path | None, dishonest: bool) -> dict:
    f = ctypes.CDLL(str(lib.resolve())).syscall_stack_admit
    f.argtypes = (ctypes.c_uint64,) * 3
    f.restype = ctypes.c_uint32
    if dishonest:
        for x in ((0, 0x120000, 0x120000),
                  (0x602000, 0x120001, 0x120001),
                  (0x602000, 0x120000, 0x120010)):
            assert oracle(*x) != 0 and f(*x) == 0
        print("dishonest native HIA SYSCALL stack gate DETECTED")
        return {"negative_control": "DETECTED"}
    counts = [0] * 4
    def run(x):
        ref = oracle(*x)
        got = f(*x)
        assert got == ref, (x, ref, got)
        counts[ref] += 1
    for u in (0, 4095, 4096, 0x602000, (1 << 47) - 1, 1 << 47, MAX64):
        for k in (0, 4096, 0x120000, 0x3ffff0, 0x120001, 0x400000, MAX64):
            for t in (0, k, k ^ 16):
                run((u, k, t))
    rng = random.Random(SEED)
    for _ in range(1200):
        k = rng.randrange(256, 0x400000 // 16) * 16
        run((rng.randrange(4096, 1 << 47), k, k))
    for _ in range(5200):
        u = rng.choice((rng.getrandbits(64), rng.randrange(4096, 1 << 47), 4095, 1 << 47))
        k = rng.choice((rng.getrandbits(64), 0x400000, 0,
                        rng.randrange(256, 0x400000 // 16) * 16))
        t = rng.choice((k, k ^ (1 << rng.randrange(52)), rng.getrandbits(64)))
        run((u, k, t))
    assert counts[0] >= 1200 and sum(counts[1:]) >= 3000, counts
    result = {
        "schema": "heptakernel.hia-syscall-stack.v1", "status": "PASS",
        "seed": SEED, "cases": sum(counts), "by_result": counts,
        "native_hia": True, "privileged_stack_switch_in_hia": False,
        "kernel_stack_provenance_authenticated": False, "smp_safe": False,
        "linux_syscall_implemented": False, "full_acceptance": "HOLD",
        "source_sha256": hashlib.sha256(Path(
            "src/x86_syscall_stack_admit.hepta").read_bytes()).hexdigest()
    }
    if obj:
        result["object_shared_text_sha256"] = code_hash(obj, lib)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    a = parser.parse_args()
    report = check(a.library, a.object, a.expect_unsafe)
    if not a.expect_unsafe:
        Path("build/x86-syscall-stack-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")
        print("HIA-native SYSCALL stack:", json.dumps(report, sort_keys=True))
