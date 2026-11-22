#!/usr/bin/env python3
"""Independent six-register oracle for actual native HIA SYSCALL frame preflight.

Snapshots are not authenticated, and this does not execute privileged instructions.
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

SEED = 0x5A4ED011
U64 = (1 << 64) - 1
FORBIDDEN = 18446744073709548840

def oracle(rip, rcx, flags, r11, rsp, saved_rsp):
    if not 4096 <= rip < (1 << 47):
        return 1
    if not 4096 <= rsp < (1 << 47):
        return 2
    if flags & 514 != 514 or flags & FORBIDDEN:
        return 3
    if rip != rcx:
        return 4
    if flags != r11:
        return 5
    if rsp != saved_rsp:
        return 6
    return 0

def text_hash(obj: Path, library: Path) -> str:
    digests = []
    with tempfile.TemporaryDirectory() as d:
        for n, path in enumerate((obj, library)):
            output = Path(d) / str(n)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(path.resolve()), str(output)], check=True,
                           capture_output=True, timeout=20)
            contents = output.read_bytes()
            assert contents, "empty native machine text"
            digests.append(hashlib.sha256(contents).hexdigest())
    assert digests[0] == digests[1], "native object/shared text mismatch"
    return digests[0]

def check(lib: Path, obj: Path | None, dishonest: bool) -> dict:
    f = ctypes.CDLL(str(lib.resolve())).syscall_return_frame_admit
    f.argtypes = (ctypes.c_uint64,) * 6
    f.restype = ctypes.c_uint32
    base = (0x400002, 0x400002, 0x202, 0x202, 0x602000, 0x602000)
    if dishonest:
        for broken in (
            (0, base[1], base[2], base[3], base[4], base[5]),
            (base[0], base[1] ^ 1, base[2], base[3], base[4], base[5]),
            (base[0], base[1], base[2], base[3] ^ 1, base[4], base[5]),
            (base[0], base[1], base[2], base[3], base[4], base[5] ^ 1),
        ):
            assert oracle(*broken) != 0 and f(*broken) == 0
        print("dishonest HIA SYSCALL return-frame control DETECTED")
        return {"negative_control": "DETECTED"}
    counts = [0] * 7

    def run(values):
        expected = oracle(*values)
        got = f(*values)
        assert got == expected, (values, expected, got)
        counts[expected] += 1

    run(base)
    for pos in range(6):
        for value in (0, 1, 4095, 4096, 0x202, 0x400002,
                      0x602000, (1 << 47) - 1, 1 << 47, U64):
            values = list(base)
            values[pos] = value
            run(tuple(values))
    rng = random.Random(SEED)
    for _ in range(3000):
        rip = rng.randrange(4096, 1 << 47)
        rsp = rng.randrange(4096, 1 << 47)
        flags = rng.choice((0x202, 0x206, 0x242, 0x246))
        run((rip, rip, flags, flags, rsp, rsp))
    for _ in range(6500):
        rip = rng.choice((rng.getrandbits(64), rng.randrange(4096, 1 << 47), 4095, 1 << 47))
        rsp = rng.choice((rng.getrandbits(64), rng.randrange(4096, 1 << 47), 0, 1 << 47))
        flags = rng.choice((0x202, 0x246, rng.getrandbits(64), 0, 0x302))
        rcx = rng.choice((rip, rip ^ (1 << rng.randrange(64)), rng.getrandbits(64)))
        r11 = rng.choice((flags, flags ^ (1 << rng.randrange(64)), rng.getrandbits(64)))
        saved_rsp = rng.choice((rsp, rsp ^ (1 << rng.randrange(64)), rng.getrandbits(64)))
        run((rip, rcx, flags, r11, rsp, saved_rsp))
    assert counts[0] >= 3000 and all(c > 0 for c in counts[1:]), counts
    result = {"schema": "heptakernel.hia-syscall-return-frame.v1",
              "status": "PASS", "seed": SEED, "cases": sum(counts),
              "by_result": counts, "native_hia": True,
              "hardware_state_authenticated": False,
              "privileged_return_in_hia": False,
              "smp_safe": False, "linux_syscall_implemented": False,
              "full_acceptance": "HOLD",
              "source_sha256": hashlib.sha256(Path(
                  "src/x86_syscall_return_frame.hepta").read_bytes()).hexdigest()}
    if obj is not None:
        result["object_shared_text_sha256"] = text_hash(obj, lib)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    a = parser.parse_args()
    report = check(a.library, a.object, a.expect_unsafe)
    if not a.expect_unsafe:
        Path("build/x86-syscall-return-frame-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")
        print("HIA-native SYSCALL return-frame:", json.dumps(report, sort_keys=True))
