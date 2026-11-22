#!/usr/bin/env python3
"""Bit-exact independent host oracle for bounded HIA task snapshot syscall routing.

Read-only caller-supplied two-record fixture, not a live Linux task or namespace.
The native routine must never write the supplied task bytes or guard sentinels.
"""
import argparse
import ctypes
import hashlib
import json
import random
import struct
import subprocess
import tempfile
from pathlib import Path

U64 = (1 << 64) - 1
ENOSYS, ESRCH, EINVAL = U64 - 37, U64 - 2, U64 - 21
SEED = 2026112202
KNOWN = (39, 110, 186)

def pack(rows):
    return b"".join(struct.pack("<QQQQ", *r) for r in rows)

def oracle(nr, slot, data):
    if nr not in KNOWN:
        return ENOSYS
    if len(data) != 64:
        return EINVAL
    if slot > 1:
        return ESRCH
    this = struct.unpack_from("<QQQQ", data, slot * 32)
    peer = struct.unpack_from("<QQQQ", data, (1 - slot) * 32)
    tid, tgid, ppid, live = this
    ptid, ptgid, _, plive = peer
    if (not 1 <= tid <= 2147483647 or not 1 <= tgid <= 2147483647
            or ppid > 2147483647 or live != 1):
        return ESRCH
    if tid != tgid and not (ptid == tgid and ptgid == tgid and plive == 1):
        return ESRCH
    if plive == 1 and ptid == tid:
        return ESRCH
    return {39: tgid, 110: ppid, 186: tid}[nr]

def verify_text(obj, lib):
    with tempfile.TemporaryDirectory() as d:
        sha = []
        for i, file in enumerate((obj, lib)):
            dst = Path(d) / str(i)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(file.resolve()), str(dst)], check=True,
                           capture_output=True, timeout=20)
            raw = dst.read_bytes()
            assert raw, "empty HIA text"
            sha.append(hashlib.sha256(raw).hexdigest())
        assert sha[0] == sha[1], "native object/shared .text mismatch"
        return sha[0]

def run(path, obj=None, dishonest=False):
    fn = ctypes.CDLL(str(path.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    def invoke(nr, slot, rows, request_len=16, reply_len=8):
        # Three exact buffer capabilities with independent canary guards.
        reqbytes = struct.pack("<QQ", nr, slot)
        req = ctypes.create_string_buffer(b"\x9b" * 32 + reqbytes + b"\x9b" * 32)
        out = ctypes.create_string_buffer(b"\xae" * (32 + reply_len + 32))
        state = ctypes.create_string_buffer(b"\xc3" * 32 + rows + b"\xc3" * 32)
        old_req, old_state, old_out = bytes(req), bytes(state), bytes(out)
        status = fn(ctypes.addressof(req) + 32, request_len,
                    ctypes.addressof(out) + 32, reply_len,
                    ctypes.addressof(state) + 32, len(rows))
        assert bytes(req) == old_req and bytes(state) == old_state, "read-only capability mutated"
        assert bytes(out)[:32] == old_out[:32] and bytes(out)[32 + reply_len:] == old_out[32 + reply_len:], "reply canary corrupted"
        if status == 0:
            assert reply_len >= 8 and request_len == 16
            assert bytes(out)[40:32 + reply_len] == old_out[40:32 + reply_len], "reply suffix changed"
            return int.from_bytes(bytes(out)[32:40], "little")
        assert status == (1 if request_len != 16 else 2), ("incorrect buffer reject", status)
        assert bytes(out) == old_out, "rejected output mutated"
        return None
    leader = (4242, 4242, 1, 1)
    worker = (4243, 4242, 1, 1)
    good = pack((leader, worker))
    if dishonest:
        for nr, slot, rows in [(186, 1, good), (110, 1, good),
                               (39, 2, good), (39, 1, good[:-1]),
                               (1024, 0, good)]:
            got = invoke(nr, slot, rows)
            assert got != oracle(nr, slot, rows), (nr, slot, "dishonest component passed")
        print("Dishonest HIA constant-pid control DETECTED")
        return

    counts = {"pid":0, "tid":0, "ppid":0,
              "enosys":0, "einval":0, "esrch":0}
    total = 0
    def check(nr, slot, data):
        nonlocal total
        got = invoke(nr, slot, data)
        want = oracle(nr, slot, data)
        assert got == want, (nr, slot, data.hex(), hex(got), hex(want))
        key = ("enosys" if want == ENOSYS else "einval" if want == EINVAL
               else "esrch" if want == ESRCH else
               "pid" if nr == 39 else "tid" if nr == 186 else "ppid")
        counts[key] += 1
        total += 1

    rng = random.Random(SEED)
    for _ in range(768):
        tgid = rng.randrange(1, 2147483646)
        tid = tgid + 1
        rows = pack(((tgid,tgid,rng.randrange(0,2147483648),1),
                     (tid,tgid,rng.randrange(0,2147483648),1)))
        for nr in KNOWN:
            check(nr,0,rows)
            check(nr,1,rows)
    for _ in range(7000):
        kind = rng.randrange(12)
        mutated = [list(leader),list(worker)]
        if kind == 0: mutated[0][0] = 0
        if kind == 1: mutated[1][0] = U64
        if kind == 2: mutated[1][1] = 8000
        if kind == 3: mutated[0][3] = 0
        if kind == 4: mutated[1][3] = 0
        if kind == 5: mutated[1][0] = 4242
        if kind == 6: mutated[1][2] = U64
        if kind == 7: mutated[0][1] = 9000
        if kind == 8: mutated[0][3] = 2
        if kind == 9: mutated[0][0] = 2147483648
        if kind == 10: mutated[1][1] = 2147483648
        if kind == 11: mutated[0][2] = 2147483648
        data = pack(mutated)
        nr = rng.choice((39,39,110,186,1024,0,U64))
        slot = rng.choice((0,1,1,2,U64))
        check(nr,slot,data)
    for _ in range(1024):
        nr = rng.choice(KNOWN)
        size = rng.choice((0,1,8,31,32,63,65,66,128))
        check(nr,rng.choice((0,1,2)),bytes(rng.getrandbits(8) for _ in range(size)))
    for nr in KNOWN+(0,1024,U64):
        for slot in (0,1,2,U64):
            check(nr,slot,good)
    assert total > 12000 and min(counts.values()) > 100, counts
    report = {
        "schema":"heptakernel.hia-task-snapshot-syscalls.v1",
        "status":"PASS", "seed":SEED, "cases":total, "by_result":counts,
        "native_hia":True, "task_data_authenticated":False,
        "thread_group_runtime":False, "privileged_entry_in_hia":False,
        "full_linux_abi_complete":False, "full_acceptance":"HOLD",
        "source_sha256":hashlib.sha256(Path("src/x86_syscall_task_view.hepta").read_bytes()).hexdigest()
    }
    if obj is not None:
        report["object_shared_text_sha256"] = verify_text(obj,path)
    Path("build/x86-syscall-task-view-report.json").write_text(
        json.dumps(report, indent=2,sort_keys=True)+"\n")
    print("HIA-native task-snapshot syscall view:",json.dumps(report,sort_keys=True))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("library",type=Path)
    parser.add_argument("--object",type=Path)
    parser.add_argument("--expect-unsafe",action="store_true")
    args = parser.parse_args()
    run(args.library,args.object,args.expect_unsafe)
