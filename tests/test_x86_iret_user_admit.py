#!/usr/bin/env python3
"""Independent x86-64 initial IRETQ frame oracle for genuine native HIA.

Only a fixed single-CPU 0x33/0x3b selector profile. No HIA IRETQ opcode,
no authenticated CR3, mapping provenance, IRQ ownership or Linux execve.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile

TOP = 1 << 47
MASK64 = (1 << 64) - 1
ALLOWED = 0xAD7
SEED = 0x1E7A2026

def oracle(rip, rsp, flags, cs, ss):
    if not 4096 <= rip < TOP:
        return 1
    if not 8192 <= rsp < TOP or (rsp & 15):
        return 2
    if cs != 0x33 or ss != 0x3b:
        return 3
    if (flags & 2) != 2 or flags & (MASK64 ^ ALLOWED):
        return 4
    base = (rsp - 1) & ~4095
    if base <= rip < base + 4096:
        return 5
    return 0

def text_hash(object_path, library_path):
    with tempfile.TemporaryDirectory(prefix="hia-iret-text-") as directory:
        digests = []
        for index, path in enumerate((object_path, library_path)):
            target = Path(directory) / str(index)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(path.resolve()), str(target)], check=True,
                           capture_output=True, timeout=20)
            data = target.read_bytes()
            assert data, "missing native object text"
            digests.append(hashlib.sha256(data).hexdigest())
        assert digests[0] == digests[1], "native ELF text mismatched after linking"
        return digests[0]

def run(library, object_path, dishonest):
    fn = ctypes.CDLL(str(library.resolve())).iret_user_admit
    fn.argtypes = [ctypes.c_uint64] * 5
    fn.restype = ctypes.c_uint32
    rng = random.Random(SEED)
    good = (0x401000, 0x601f80, 0x2, 0x33, 0x3b)
    cases = [good, (0x401000, 0x602000, 0x202, 0x33, 0x3b)]
    for _ in range(3200):
        rsp = rng.randrange(2, TOP // 16) * 16
        rip = rng.randrange(4096, TOP)
        if ((rsp - 1) & ~4095) <= rip < (((rsp - 1) & ~4095) + 4096):
            rip = 0x401000
            if rip == (rsp - 1) & ~4095:
                rip = 0x501000
        cases.append((rip, rsp, rng.choice((2, 0x202, 0xAD7)), 0x33, 0x3b))
    for _ in range(1600):
        cases.append((rng.choice((0, 1, 4095, TOP, TOP+1, MASK64)),
                      good[1], good[2], good[3], good[4]))
    for _ in range(1600):
        cases.append((good[0], rng.choice((0, 4096, 8191, 8193, TOP, MASK64)),
                      good[2], good[3], good[4]))
    for _ in range(1600):
        cases.append((good[0], good[1], good[2],
                      rng.choice((0, 0x08, 0x23, 0x30, 0x43, 0x133)),
                      rng.choice((0x3b, 0x10, 0, 0x2b))))
    for _ in range(1600):
        cases.append((good[0], good[1],
                      rng.choice((0, 0x200, 0x302, 0x1002, 0x402, MASK64)),
                      good[3], good[4]))
    for _ in range(1600):
        rsp = rng.choice((0x601f80, 0x602000, 0x602f80))
        base = (rsp - 1) & ~4095
        cases.append((rng.randrange(base, base+4096), rsp,
                      0x202, good[3], good[4]))
    counts = [0] * 6
    divergent = 0
    for values in cases:
        expected = oracle(*values)
        actual = fn(*values)
        counts[expected] += 1
        divergent += actual != expected
        if not dishonest:
            assert actual == expected, (values, expected, actual)
    if dishonest:
        assert divergent >= 5000, ("dishonest HIA IRETQ gate escaped", divergent)
        print("HIA_IRET_USER_DISHONEST_CONTROL: DETECTED", divergent)
        return
    assert counts[0] >= 3000 and all(n >= 1000 for n in counts[1:]), counts
    report = {"schema": "heptakernel.hia-iret-user-preflight.v1",
              "seed": SEED, "cases": len(cases), "by_status": counts,
              "source_sha256": hashlib.sha256(Path(
                  "src/x86_iret_user_admit.hepta").read_bytes()).hexdigest(),
              "native_hia_scalar_preflight": True,
              "iretq_opcode_in_hia_backend": False,
              "authenticated_cpu_or_page_table": False,
              "linux_execve": False, "full_linux": "HOLD", "status": "PASS"}
    if object_path:
        report["object_shared_text_sha256"] = text_hash(object_path, library)
    Path("build/x86-iret-user-admit-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("HIA_IRET_USER_NATIVE_ORACLE: PASS", json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--dishonest", action="store_true")
    args = parser.parse_args()
    run(args.library, args.object, args.dishonest)
