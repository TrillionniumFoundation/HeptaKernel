#!/usr/bin/env python3
"""Independent exact-value oracle for true native HIA SYSCALL MSR admission.

These are *caller-supplied* MSR snapshots, not RDMSR, WRMSR, SYSCALL,
privilege transitions or a Linux syscall implementation.
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

U64 = (1 << 64) - 1
KERNEL_BASE = 0xFFFF800000000000
KERNEL_END = 0xFFFFFFFFFFFFF000  # exclude the top canonical page
STAR = (0x30 << 48) | (0x08 << 32)  # SYSRET CS=0x43, SS=0x3b; SYSCALL CS=0x08
FMASK = (1 << 8) | (1 << 9) | (1 << 10) | (3 << 12) | (1 << 14) | (1 << 18)
EFER = (1 << 0) | (1 << 8) | (1 << 10) | (1 << 11)
SEED = 0x53C411


def oracle(lstar: int, star: int, fmask: int, efer: int) -> int:
    if not KERNEL_BASE <= lstar < KERNEL_END:
        return 1
    if star != STAR:
        return 2
    if (fmask & FMASK) != FMASK:
        return 3
    if (efer & EFER) != EFER:
        return 4
    return 0


def text_identity(obj: Path, so: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="syscall-msr-text-") as d:
        hashes = []
        for name, p in (("obj", obj), ("so", so)):
            output = Path(d) / name
            subprocess.run(
                ["objcopy", "--only-section=.text", "-O", "binary",
                 str(p.resolve()), str(output)],
                check=True, capture_output=True, timeout=20)
            data = output.read_bytes()
            assert data, "HIA .text absent"
            hashes.append(hashlib.sha256(data).hexdigest())
        assert hashes[0] == hashes[1], "HIA .text changed in shared linking"
        return hashes[0]


def run(library: Path, obj: Path | None, expect_unsafe: bool) -> dict:
    native = ctypes.CDLL(str(library.resolve())).syscall_msr_admit
    native.argtypes = (ctypes.c_uint64,) * 4
    native.restype = ctypes.c_uint32
    if expect_unsafe:
        bad = [(0, STAR, FMASK, EFER), (KERNEL_BASE, 0, FMASK, EFER),
               (KERNEL_BASE, STAR, 0, EFER),
               (KERNEL_BASE, STAR, FMASK, 0)]
        assert all(oracle(*case) != 0 for case in bad)
        assert all(native(*case) == 0 for case in bad), "dishonest control changed"
        print("dishonest native HIA SYSCALL MSR gate: DETECTED BY ORACLE")
        return {"negative_control": "DETECTED"}

    accepted = refused = checked = 0

    def check(case: tuple[int, int, int, int]) -> None:
        nonlocal accepted, refused, checked
        expected = oracle(*case)
        actual = native(*case)
        assert actual == expected, (tuple(hex(x) for x in case), expected, actual)
        checked += 1
        accepted += expected == 0
        refused += expected != 0

    valid_targets = (KERNEL_BASE, KERNEL_BASE + 1,
                     0xFFFFFFFF81000000, KERNEL_END - 1)
    for target in valid_targets:
        for mask in (FMASK, FMASK | 1, FMASK | (1 << 63)):
            for enabled in (EFER, EFER | 2, EFER | (1 << 63)):
                check((target, STAR, mask, enabled))
    # Each bit of STAR and of mandatory FMASK/EFER has a separate rejection.
    for bit in range(64):
        check((KERNEL_BASE, STAR ^ (1 << bit), FMASK, EFER))
        check((KERNEL_BASE, STAR, FMASK ^ (1 << bit), EFER))
        check((KERNEL_BASE, STAR, FMASK, EFER ^ (1 << bit)))
    for value in (0, 1, 4096, (1 << 47) - 1, 1 << 47,
                  KERNEL_BASE - 1, KERNEL_END, U64):
        check((value, STAR, FMASK, EFER))
    rng = random.Random(SEED)
    # Lots of legitimate high-half entry profiles with independent extra bits.
    for _ in range(400):
        lstar = rng.randrange(KERNEL_BASE, KERNEL_END)
        mask = FMASK | rng.getrandbits(64)
        efer = EFER | rng.getrandbits(64)
        check((lstar, STAR, mask, efer))
    # Adversarial false positives and stale/mismatched field mixtures.
    for _ in range(5600):
        lstar = rng.choice([rng.getrandbits(64),
                            rng.randrange(KERNEL_BASE, KERNEL_END),
                            KERNEL_BASE - 1, KERNEL_END, U64])
        star = rng.choice([STAR, STAR ^ (1 << rng.randrange(64)),
                           rng.getrandbits(64)])
        fmask = rng.choice([FMASK, FMASK ^ (1 << rng.randrange(64)),
                            rng.getrandbits(64)])
        efer = rng.choice([EFER, EFER ^ (1 << rng.randrange(64)),
                           rng.getrandbits(64)])
        check((lstar, star, fmask, efer))
    assert accepted >= 430 and refused >= 4500, (accepted, refused)
    report = {
        "schema": "heptakernel.x86-syscall-msr-admission.v1",
        "status": "PASS", "native_hia": True, "seed": SEED,
        "cases": checked, "accepted": accepted, "refused": refused,
        "source_sha256": hashlib.sha256(
            Path("src/x86_syscall_msr_admit.hepta").read_bytes()).hexdigest(),
        "msr_provenance_authenticated": False,
        "privileged_instruction_emitted": False,
        "hardware_syscall_executed": False,
        "linux_syscall_implemented": False, "full_acceptance": "HOLD",
    }
    if obj is not None:
        report["object_shared_text_sha256"] = text_identity(obj, library)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    report = run(args.library, args.object, args.expect_unsafe)
    if not args.expect_unsafe:
        Path("build/x86-syscall-msr-admit-report.json").write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print("Native HIA SYSCALL MSR preflight:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
