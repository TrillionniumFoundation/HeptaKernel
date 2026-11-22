#!/usr/bin/env python3
"""Independent oracle for single-owner HIA two-record task lifecycle transitions.

No real scheduler, PID namespace, atomics or Linux clone/exit ABI is implied.
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
MAX_PID = (1 << 31) - 1
SEED = 2026112203
EMPTY = (0, 0, 0, 0)


def pack_rows(rows):
    return struct.pack("<8Q", *(w for row in rows for w in row))


def oracle(req, reply_length, before):
    if len(req) != 32:
        return 1, before, None
    if reply_length != 8:
        return 2, before, None
    if len(before) != 64:
        return 3, before, None
    op, leader_expected, old_worker, new_worker = struct.unpack("<4Q", req)
    if op not in (0, 1):
        return 4, before, None
    leader = struct.unpack_from("<4Q", before, 0)
    worker = struct.unpack_from("<4Q", before, 32)
    tid, tgid, parent, active = leader
    if not (1 <= tid <= MAX_PID and tgid == tid and parent <= MAX_PID
            and active == 1 and tid == leader_expected):
        return 5, before, None
    if op == 0:
        if worker != EMPTY or old_worker != 0:
            return 6, before, None
        if not 1 <= new_worker <= MAX_PID or new_worker == tid:
            return 7, before, None
        result = new_worker
        replacement = (result, tid, parent, 1)
    else:
        if not (1 <= old_worker <= MAX_PID
                and worker == (old_worker, tid, parent, 1)):
            return 6, before, None
        if new_worker != 0:
            return 7, before, None
        result = 0
        replacement = EMPTY
    return 0, before[:32] + struct.pack("<4Q", *replacement), result


def text_hash(obj, lib):
    with tempfile.TemporaryDirectory() as td:
        hashes = []
        for index, path in enumerate((obj, lib)):
            rawpath = Path(td) / str(index)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(path.resolve()), str(rawpath)], check=True,
                           timeout=20, capture_output=True)
            data = rawpath.read_bytes()
            assert data, "empty native HIA .text"
            hashes.append(hashlib.sha256(data).hexdigest())
        assert hashes[0] == hashes[1], "object/shared native .text differs"
        return hashes[0]


def setup(path):
    fun = ctypes.CDLL(str(path.resolve())).f0
    fun.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fun.restype = ctypes.c_uint32
    return fun


def invoke(fun, req, before, reply_length=8):
    guarded_req = ctypes.create_string_buffer(b"\x91" * 32 + req + b"\x91" * 32)
    guarded_state = ctypes.create_string_buffer(b"\xa3" * 32 + before + b"\xa3" * 32)
    guarded_out = ctypes.create_string_buffer(b"\xb5" * (32 + reply_length + 32))
    old_req, old_out = bytes(guarded_req), bytes(guarded_out)
    rc = fun(ctypes.addressof(guarded_req) + 32, len(req),
             ctypes.addressof(guarded_out) + 32, reply_length,
             ctypes.addressof(guarded_state) + 32, len(before))
    assert bytes(guarded_req) == old_req, "request mutated"
    assert bytes(guarded_state)[:32] == b"\xa3" * 32, "state prefix guard damaged"
    assert bytes(guarded_state)[32+len(before):] == b"\xa3" * 32, "state suffix guard damaged"
    assert bytes(guarded_out)[:32] == b"\xb5" * 32, "reply prefix guard damaged"
    assert bytes(guarded_out)[32+reply_length:] == b"\xb5" * 32, "reply suffix guard damaged"
    updated = bytes(guarded_state)[32:32+len(before)]
    if rc:
        assert bytes(guarded_out) == old_out, "failure changed reply"
    else:
        assert reply_length == 8, "success with invalid reply shape"
    result = int.from_bytes(bytes(guarded_out)[32:40], "little") if rc == 0 else None
    return rc, updated, result


def check_view(view, rows, expected):
    req = struct.pack("<QQ", 186, 1)
    request = ctypes.create_string_buffer(req)
    output = ctypes.create_string_buffer(8)
    state = ctypes.create_string_buffer(rows)
    old = bytes(state)
    status = view(ctypes.addressof(request), 16,
                  ctypes.addressof(output), 8,
                  ctypes.addressof(state), 64)
    assert status == 0 and bytes(state) == old
    actual = struct.unpack("<Q", bytes(output))[0]
    assert actual == expected, (actual, expected)


def run(native, view_path, obj, dishonest):
    fun = setup(native)
    view = setup(view_path) if view_path and not dishonest else None
    leader = (4242, 4242, 1, 1)
    empty_rows = pack_rows((leader, EMPTY))
    active_rows = pack_rows((leader, (4243, 4242, 1, 1)))
    base_samples = [
        (struct.pack("<4Q", 0, 4242, 0, 4243), empty_rows, 8),
        (struct.pack("<4Q", 1, 4242, 4243, 0), active_rows, 8),
        (struct.pack("<4Q", 0, 4242, 0, 4243), active_rows, 8),
        (struct.pack("<4Q", 1, 4242, 999, 0), active_rows, 8),
        (struct.pack("<4Q", 0, 4242, 0, 4242), empty_rows, 8),
        (struct.pack("<4Q", 1, 4242, 4243, 123), active_rows, 8),
        (struct.pack("<4Q", 0, 4444, 0, 4243), empty_rows, 8),
        (struct.pack("<4Q", 9, 4242, 0, 4243), empty_rows, 8),
        (b"\x00" * 16, empty_rows, 8),
        (struct.pack("<4Q", 0, 4242, 0, 4243), empty_rows, 3),
        (struct.pack("<4Q", 0, 4242, 0, 4243), empty_rows[:-1], 8),
    ]
    if dishonest:
        mismatches = 0
        for req, rows, size in base_samples:
            want = oracle(req, size, rows)
            got = invoke(fun, req, rows, size)
            mismatches += (want != got)
        assert mismatches >= 3, "dishonest no-op HIA went undetected"
        print("Dishonest native HIA no-op task lifecycle DETECTED", mismatches)
        return

    rng = random.Random(SEED)
    counts = {str(i): 0 for i in range(8)}
    total = 0

    def check(req, rows, size=8):
        nonlocal total
        want = oracle(req, size, rows)
        got = invoke(fun, req, rows, size)
        assert got == want, (req.hex(), rows.hex(), size, got, want)
        counts[str(want[0])] += 1
        total += 1
        return got

    for req, rows, size in base_samples:
        check(req, rows, size)
    for _ in range(1152):
        leader_tid = rng.randrange(1, MAX_PID-1)
        parent = rng.randrange(0, MAX_PID+1)
        new_tid = leader_tid + 1
        original = pack_rows(((leader_tid, leader_tid, parent, 1), EMPTY))
        spawn = struct.pack("<4Q", 0, leader_tid, 0, new_tid)
        spawned = check(spawn, original)
        assert spawned[2] == new_tid and spawned[1] != original
        exit_request = struct.pack("<4Q", 1, leader_tid, new_tid, 0)
        retired = check(exit_request, spawned[1])
        assert retired[1] == original and retired[2] == 0
        if view is not None:
            check_view(view, spawned[1], new_tid)
            check_view(view, retired[1], U64 - 2)
    for _ in range(7800):
        leader_tid = rng.randrange(1, 25000)
        parent = rng.randrange(0, 25000)
        leader_row = [leader_tid, leader_tid, parent, 1]
        worker_row = [leader_tid+1, leader_tid, parent, 1]
        op = rng.randrange(0, 5)
        expected_leader = leader_tid
        old_worker = worker_row[0]
        new_worker = 0
        kind = rng.randrange(16)
        if kind == 0: leader_row[0] = 0
        if kind == 1: leader_row[1] = 0
        if kind == 2: leader_row[2] = U64
        if kind == 3: leader_row[3] = 0
        if kind == 4: expected_leader += 1
        if kind == 5: worker_row[0] = U64
        if kind == 6: worker_row[1] += 1
        if kind == 7: worker_row[2] += 1
        if kind == 8: worker_row[3] = 2
        if kind == 9: old_worker = 0
        if kind == 10: new_worker = leader_tid+9
        if kind == 11: op = 0
        if kind == 12: worker_row = list(EMPTY); op = 0; old_worker = 0; new_worker = leader_tid
        if kind == 13: worker_row = list(EMPTY); op = 0; old_worker = 0; new_worker = U64
        if kind == 14: worker_row = list(EMPTY); op = 0; old_worker = 0; new_worker = leader_tid+1
        if kind == 15: op = 1; new_worker = 0
        req = struct.pack("<4Q", op, expected_leader, old_worker, new_worker)
        check(req, pack_rows((leader_row, worker_row)))
    for _ in range(1200):
        size = rng.choice((0, 1, 2, 8, 16, 24, 31, 33, 64))
        req = bytes(rng.getrandbits(8) for _ in range(size))
        check(req, empty_rows, rng.choice((0, 8)))
    for _ in range(1300):
        size = rng.choice((0, 1, 3, 7, 9, 16, 63, 65, 96))
        state = bytes(rng.getrandbits(8) for _ in range(size))
        check(struct.pack("<4Q", 1, 4242, 4243, 0), state)
    assert total >= 12000, total
    assert min(counts.values()) > 0, counts
    report = {"schema": "heptakernel.hia-task-lifecycle.v1",
              "seed": SEED, "cases": total, "by_status": counts,
              "status": "PASS", "native_hia": True,
              "single_owner_only": True, "hardware_task_source": False,
              "atomic_multiword_transaction": False, "linux_clone_exit": False,
              "full_acceptance": "HOLD",
              "source_sha256": hashlib.sha256(
                  Path("src/x86_task_lifecycle.hepta").read_bytes()).hexdigest()}
    if obj:
        report["object_shared_text_sha256"] = text_hash(obj, native)
    Path("build/x86-task-lifecycle-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("HIA-native two-slot task lifecycle:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("native", type=Path)
    ap.add_argument("--view", type=Path)
    ap.add_argument("--object", type=Path)
    ap.add_argument("--expect-unsafe", action="store_true")
    args = ap.parse_args()
    run(args.native, args.view, args.object, args.expect_unsafe)
