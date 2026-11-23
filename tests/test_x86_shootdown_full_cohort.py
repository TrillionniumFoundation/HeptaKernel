#!/usr/bin/env python3
"""Independent byte oracle for complete remote cohort; never CPU acknowledgement authority."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import random
import struct
from pathlib import Path

ROOT = 0x200000
VA = 0x400000
EPOCH = 37
ONLINE = (1 << 63) | (1 << 5) | 1
SEED = 0xC0F0C017
MASK = (1 << 64) - 1

def pack(*, root=ROOT, va=VA, epoch=EPOCH, prior=EPOCH - 1,
         online=ONLINE, after=None, issuer=0, target=None, rows=None, reserved=0):
    if after is None:
        after = online
    if target is None:
        target = online & ~(1 << issuer)
    if rows is None:
        rows = [(cpu, epoch, root, 3, va) for cpu in range(64) if target & (1 << cpu)]
    return struct.pack("<10Q", root, va, epoch, prior, online, after,
                       issuer, target, len(rows), reserved) + b"".join(
        struct.pack("<5Q", *row) for row in rows)

def oracle(data: bytes) -> int:
    if len(data) < 80:
        return 1
    root, va, epoch, prior, online, after, issuer, target, n, reserved = struct.unpack_from("<10Q", data)
    if not 0 <= n <= 64 or len(data) != 80 + 40 * n:
        return 1
    canonical = (va >> 48) == (0xffff if va & (1 << 47) else 0)
    if (root == 0 or root & 4095 or root >= 1 << 52 or va & 4095
            or not canonical or epoch == 0 or prior >= epoch
            or online == 0 or after != online or reserved != 0
            or issuer >= 64 or not online & (1 << issuer)
            or target != (online & ~(1 << issuer))):
        return 2
    if target == 0:
        return 6 if n == 0 else 2  # local-only is NOT remote-ack success
    seen = 0
    for cpu, ack_epoch, ack_root, flags, ack_va in struct.iter_unpack("<5Q", data[80:]):
        if cpu >= 64 or not target & (1 << cpu) or seen & (1 << cpu):
            return 3
        if ack_epoch != epoch or ack_root != root or flags != 3 or ack_va != va:
            return 4
        seen |= 1 << cpu
    return 0 if seen == target else 5

def cases():
    base = [(5, EPOCH, ROOT, 3, VA), (63, EPOCH, ROOT, 3, VA)]
    high = 0xffff800000004000
    yield pack()
    yield pack(rows=list(reversed(base)))
    yield pack(online=MASK)
    yield pack(online=1, issuer=0)    # local-only: status 6
    yield pack(online=(1 << 63), issuer=63)
    yield pack(online=1, issuer=0, rows=[(0, EPOCH, ROOT, 3, VA)])  # bogus local ack
    yield pack(online=1, issuer=0, target=1, rows=[(0, EPOCH, ROOT, 3, VA)])
    yield pack(online=ONLINE, rows=[])  # missing remote rows
    yield pack(online=(1 << 63) | 1, issuer=63)
    yield pack(va=high, rows=[(cpu, EPOCH, ROOT, 3, high) for cpu in (5, 63)])
    yield pack(target=1 << 5)             # original undercoverage vulnerability
    yield pack(after=ONLINE ^ (1 << 63)) # online changed during request
    yield pack(prior=EPOCH)             # replay
    yield pack(prior=EPOCH + 1)         # epoch reversal
    yield pack(issuer=64)
    yield pack(reserved=1)
    yield pack(online=1, issuer=0)
    yield pack(rows=base[:1])          # CPU 63 is still required
    yield pack(rows=[base[0], base[0]])
    yield pack(rows=[(64, EPOCH, ROOT, 3, VA), base[1]])
    yield pack(rows=[(5, EPOCH - 1, ROOT, 3, VA), base[1]])
    yield pack(rows=[(5, EPOCH, ROOT ^ 4096, 3, VA), base[1]])
    yield pack(rows=[(5, EPOCH, ROOT, 2, VA), base[1]])
    yield pack(rows=[(5, EPOCH, ROOT, 3, VA + 4096), base[1]])
    yield pack(va=VA + 4096, rows=base)
    yield pack(root=0)
    yield pack(va=VA + 1)
    yield pack(va=1 << 48)
    yield pack(epoch=0, prior=0)
    yield pack(rows=[])
    yield b""
    yield b"\x00" * 79
    yield pack() + b"\x00"
    rng = random.Random(SEED)
    for _ in range(2500):
        ids = sorted(rng.sample(range(64), rng.randrange(2, 65)))
        online = sum(1 << cpu for cpu in ids)
        issuer = rng.choice(ids)
        target = online & ~(1 << issuer)
        root = rng.randrange(1, 1 << 35) << 12
        epoch = rng.randrange(1, 1 << 64)
        va = rng.choice((0, VA, high, 0xfffffffffffff000))
        rows = [(cpu, epoch, root, 3, va) for cpu in ids if cpu != issuer]
        rng.shuffle(rows)
        yield pack(root=root, va=va, epoch=epoch, prior=epoch - 1,
                   online=online, issuer=issuer, target=target, rows=rows)
    for _ in range(3600):
        ids = sorted(rng.sample(range(64), rng.randrange(2, 20)))
        online = sum(1 << cpu for cpu in ids)
        issuer = rng.choice(ids)
        target = online & ~(1 << issuer)
        root = rng.randrange(1, 1 << 35) << 12
        epoch = rng.randrange(2, 1 << 64)
        va = rng.choice((VA, 0x800000, high))
        rows = [(cpu, epoch, root, 3, va) for cpu in ids if cpu != issuer]
        kw = dict(root=root, va=va, epoch=epoch, prior=epoch - 1,
                  online=online, issuer=issuer, target=target)
        fault = rng.randrange(16)
        if fault == 0: rows[-1] = rows[0]
        elif fault == 1: rows[0] = (64, epoch, root, 3, va)
        elif fault == 2: rows[0] = (rows[0][0], epoch - 1, root, 3, va)
        elif fault == 3: rows[0] = (rows[0][0], epoch, root ^ 4096, 3, va)
        elif fault == 4: rows[0] = (rows[0][0], epoch, root, 2, va)
        elif fault == 5: rows[0] = (rows[0][0], epoch, root, 3, va ^ 4096)
        elif fault == 6: rows.pop()
        elif fault == 7: kw["va"] = va ^ 4096
        elif fault == 8: kw["root"] = 0
        elif fault == 9: kw["target"] = target ^ (1 << rows[-1][0])
        elif fault == 10: kw["after"] = online ^ (1 << ids[-1])
        elif fault == 11: kw["prior"] = epoch
        elif fault == 12: kw["issuer"] = 64
        elif fault == 13: kw["reserved"] = 1
        elif fault == 14: kw["target"] = target | (1 << issuer)
        else: kw["online"] = 1 << issuer
        yield pack(rows=rows, **kw)

def campaign(library: Path, dishonest: bool) -> None:
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    counts = [0] * 7
    violations = 0
    n = 0
    for raw in cases():
        n += 1
        expected = oracle(raw)
        source = ctypes.create_string_buffer(b"\xa7" * 32 + raw + b"\xa7" * 32)
        reply = ctypes.create_string_buffer(b"\xb4" * 48)
        scratch = ctypes.create_string_buffer(b"\xc3" * 48)
        before = bytes(source), bytes(reply), bytes(scratch)
        returned = native(ctypes.addressof(source) + 32, len(raw),
                          ctypes.addressof(reply), 48,
                          ctypes.addressof(scratch), 48)
        assert before == (bytes(source), bytes(reply), bytes(scratch)), "buffer mutated"
        if dishonest:
            violations += int(expected != 0 and returned == 0)
        else:
            if returned != expected:
                raise AssertionError((raw.hex()[:128], expected, returned))
            counts[returned] += 1
    if dishonest:
        assert violations >= 200, ("dishonest HIA not detected", violations)
        print("dishonest HIA full-cohort ack DETECTED", violations)
        return
    assert counts[0] >= 2500 and all(x > 0 for x in counts[1:]), counts
    assert oracle(pack(online=1, issuer=0)) == 6
    assert oracle(pack(online=(1 << 63), issuer=63)) == 6
    assert oracle(pack(online=ONLINE, rows=[])) == 5
    report = {
        "schema": "heptakernel.hia-x86-shootdown-full-cohort.v1",
        "status": "PASS", "cases": n, "seed": SEED, "status_counts": counts,
        "exact_remote_cohort_from_online_mask": True, "local_only_status": 6,
        "local_only_authorizes_reclamation": False,
        "claimed_online_and_epoch_authenticity": False, "hardware_ack_authenticated": False,
        "ipi_or_invlpg_emitted": False, "smp_safety_proven": False, "frame_reclamation_authorized": False,
        "full_linux_acceptance": "HOLD",
        "source_sha256": hashlib.sha256(Path("src/x86_shootdown_full_cohort.hepta").read_bytes()).hexdigest(),
        "object_sha256": hashlib.sha256(Path("build/x86-shootdown-full-cohort.o").read_bytes()).hexdigest(),
    }
    Path("build/x86-shootdown-full-cohort-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("full-cohort HIA shootdown claimed snapshot:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--dishonest", action="store_true")
    args = parser.parse_args()
    campaign(args.library, args.dishonest)
