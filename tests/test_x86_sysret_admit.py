#!/usr/bin/env python3
"""Independent differential oracle for true HIA-native SYSRETQ preflight.

No actual SYSRETQ, MSR sampling, privilege switching or Linux user ABI.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile

MAX64 = (1 << 64) - 1
USER_TOP = 1 << 47
USER_BOTTOM = 4096
ALLOWED = sum(1 << bit for bit in (0, 1, 2, 4, 6, 7, 9, 11))
REQUIRED = (1 << 1) | (1 << 9)
assert ALLOWED == 0xAD7 and REQUIRED == 0x202
# Fixed Linux x86 UAPI: bit 0 is CF, bit 1 FIXED, bit 3 reserved.
assert (ALLOWED & 1) and not (ALLOWED & 8)

def oracle(rip: int, rsp: int, flags: int) -> int:
    if not USER_BOTTOM <= rip < USER_TOP:
        return 1
    if not USER_BOTTOM <= rsp < USER_TOP:
        return 2
    if (flags & REQUIRED) != REQUIRED or flags & (MAX64 ^ ALLOWED):
        return 3
    return 0

def text_hash_match(object_path: Path, library_path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="hia-sysret-text-") as directory:
        digests = []
        for index, path in enumerate((object_path, library_path)):
            out = Path(directory) / str(index)
            subprocess.run(
                ["objcopy", "--only-section=.text", "-O", "binary",
                 str(path.resolve()), str(out)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=20)
            data = out.read_bytes()
            assert data, "missing native HIA text"
            digests.append(hashlib.sha256(data).hexdigest())
        assert digests[0] == digests[1], "native HIA text changed on linking"
        return digests[0]

def differential(library: Path, object_file: Path | None = None) -> dict:
    fn = ctypes.CDLL(str(library.resolve())).sysret_admit
    fn.argtypes = (ctypes.c_uint64,) * 3
    fn.restype = ctypes.c_uint32
    checked = accepted = refused = 0

    def check(rip: int, rsp: int, flags: int) -> None:
        nonlocal checked, accepted, refused
        args = (rip, rsp, flags)
        expected = oracle(*args)
        actual = fn(*args)
        assert actual == expected, (args, expected, actual)
        checked += 1
        accepted += expected == 0
        refused += expected != 0

    seed = 0x518E7A91
    rng = random.Random(seed)
    valid_rips = (USER_BOTTOM, 0x400000, USER_TOP - 1)
    valid_rsps = (USER_BOTTOM, 0x70000000, USER_TOP - 1)
    for rip in valid_rips:
        for rsp in valid_rsps:
            for f in (REQUIRED, ALLOWED, REQUIRED | 1, REQUIRED | (1 << 11)):
                check(rip, rsp, f)
    for rip in (0, 1, 4095, USER_TOP, USER_TOP + 4096,
                0xFFFF800000000000, MAX64):
        check(rip, 0x70000000, REQUIRED)
    for rsp in (0, 1, 4095, USER_TOP, USER_TOP + 4096,
                0xFFFF800000000000, MAX64):
        check(0x400000, rsp, REQUIRED)
    assert oracle(0x400000, 0x70000000, 0x203) == 0
    assert oracle(0x400000, 0x70000000, 0xAD7) == 0
    assert oracle(0x400000, 0x70000000, 0x20A) == 3
    assert oracle(0x400000, 0x70000000, 0xADF) == 3
    for flags in (0x203, 0xAD7, 0x20A, 0xADF):
        check(0x400000, 0x70000000, flags)
    for bit in range(64):
        check(0x400000, 0x70000000, REQUIRED ^ (1 << bit))
        check(0x400000, 0x70000000, ALLOWED | (1 << bit))
    for _ in range(600):
        rip = rng.randrange(USER_BOTTOM, USER_TOP)
        rsp = rng.randrange(USER_BOTTOM, USER_TOP)
        subset = ALLOWED & rng.getrandbits(64)
        check(rip, rsp, subset | REQUIRED)
    for _ in range(5200):
        rip = rng.choice([rng.getrandbits(64), rng.randrange(USER_BOTTOM, USER_TOP),
                          0, USER_TOP - 1, USER_TOP])
        rsp = rng.choice([rng.getrandbits(64), rng.randrange(USER_BOTTOM, USER_TOP),
                          0, USER_TOP - 1, USER_TOP])
        f = rng.choice([rng.getrandbits(64), REQUIRED, ALLOWED,
                        REQUIRED ^ 2, REQUIRED ^ 512,
                        REQUIRED | (1 << rng.randrange(3, 64))])
        check(rip, rsp, f)
    assert accepted >= 630 and refused >= 2000, (accepted, refused)
    report = {
        "schema": "heptakernel.hia-x86-sysret-admit.v1",
        "status": "PASS", "cases": checked, "accepted": accepted,
        "refused": refused, "seed": seed,
        "source_sha256": hashlib.sha256(Path(
            "src/x86_sysret_admit.hepta").read_bytes()).hexdigest(),
        "native_hia": True, "sysret_executed": False,
        "cpu_or_msr_state_authenticated": False,
        "linux_syscall_implemented": False, "full_acceptance": "HOLD",
    }
    if object_file is not None:
        report["object_shared_text_sha256"] = text_hash_match(object_file, library)
    return report

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        dishonest = ctypes.CDLL(str(args.library.resolve())).sysret_admit
        dishonest.argtypes = (ctypes.c_uint64,) * 3
        dishonest.restype = ctypes.c_uint32
        for case in ((0, 0x70000000, REQUIRED),
                     (0x400000, USER_TOP, REQUIRED),
                     (0x400000, 0x70000000, REQUIRED | (1 << 12))):
            assert oracle(*case) != 0
            assert dishonest(*case) == 0, "malicious control changed"
        print("dishonest native HIA SYSRETQ admission: DETECTED BY ORACLE")
        return
    report = differential(args.library, args.object)
    Path("build/x86-sysret-admit-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("Native HIA SYSRETQ candidate admission:", json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
