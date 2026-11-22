#!/usr/bin/env python3
"""Independent bit-exact host oracle for one-task HIA getpid return values.

Linux x86-64 syscall number 39 is getpid. The process identity here is
caller-supplied fixture state, NOT an authenticated kernel task. No other
syscall is counted as implemented. The negative file is separately compiled
from real HIA source and must be caught on valid and invalid requests.
"""
import argparse
import ctypes
import hashlib
import json
import random
import subprocess
import tempfile
from pathlib import Path

U64 = (1 << 64) - 1
ENOSYS = U64 - 37
ESRCH = U64 - 2
SEED = 0x40A2026

def oracle(nr, tgid):
    if nr != 39:
        return ENOSYS
    if not 1 <= tgid <= 2147483647:
        return ESRCH  # refused inconsistent caller state, not Linux getpid error contract
    return tgid

def verify_text(obj, lib):
    with tempfile.TemporaryDirectory() as d:
        digests = []
        for n, path in enumerate((obj, lib)):
            output = Path(d) / str(n)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(path.resolve()), str(output)], check=True,
                           capture_output=True, timeout=20)
            raw = output.read_bytes()
            assert raw, "empty native text"
            digests.append(hashlib.sha256(raw).hexdigest())
        assert digests[0] == digests[1], "object/shared .text mismatch"
        return digests[0]

def check(lib, obj, dishonest):
    fn = ctypes.CDLL(str(lib.resolve())).syscall_one_task
    fn.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    fn.restype = ctypes.c_uint64
    if dishonest:
        for nr, tgid in [(39, 1), (39, 0), (186, 4242), (U64, U64)]:
            assert fn(nr, tgid) != oracle(nr, tgid), "dishonest HIA unexpectedly matched oracle"
        print("Dishonest HIA always-pid control DETECTED")
        return
    counts = {"getpid": 0, "enosys": 0, "invalid_task": 0}
    def run(nr, tgid):
        want = oracle(nr, tgid)
        got = fn(nr, tgid)
        assert got == want, (nr, tgid, hex(want), hex(got))
        if nr != 39:
            counts["enosys"] += 1
        elif want == ESRCH:
            counts["invalid_task"] += 1
        else:
            counts["getpid"] += 1
    for nr in [0, 1, 2, 39, 39, 39, 60, 110, 186, 257, 1024, U64]:
        for pid in [0, 1, 2, 39, 4242, 2147483647, 2147483648, U64]:
            run(nr, pid)
    rng = random.Random(SEED)
    for _ in range(12000):
        nr = rng.choice([39, 39, 39, 0, 1, 110, 186, 257, rng.getrandbits(64)])
        pid = rng.choice([0, 1, 4242, 2147483647, 2147483648,
                          U64, rng.getrandbits(31), rng.getrandbits(64)])
        run(nr, pid)
    for _ in range(512):
        run(39, rng.randrange(1, 1 << 31))
    assert counts["getpid"] > 2000 and counts["enosys"] > 2000 and counts["invalid_task"] > 100
    result = {
        "schema": "heptakernel.hia-one-task-syscall.v1",
        "status": "PASS", "seed": SEED, "cases": sum(counts.values()),
        "by_result": counts, "source_sha256": hashlib.sha256(
            Path("src/x86_syscall_one_task.hepta").read_bytes()).hexdigest(),
        "native_hia": True, "hardware_entry_in_hia": False,
        "task_state_authenticated": False, "process_lifecycle": False,
        "other_syscalls_implemented": False, "full_acceptance": "HOLD"}
    if obj is not None:
        result["object_shared_text_sha256"] = verify_text(obj, lib)
    Path("build/x86-syscall-one-task-report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("HIA-native one-task syscall:", json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("library", type=Path)
    p.add_argument("--object", type=Path)
    p.add_argument("--expect-unsafe", action="store_true")
    a = p.parse_args()
    check(a.library, a.object, a.expect_unsafe)
