#!/usr/bin/env python3
"""Independent byte-level oracle for page-bound, UNTRUSTED shootdown claims.

This tests the 40-byte ack row's requested virtual-page identity binding.
No actual remote CPU, CR3, IPI, memory-ordering, or TLB authority is inferred.
"""
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
SEED = 0x71BCB011
MASK = (1 << 64) - 1


def pack(*, root=ROOT, va=VA, epoch=EPOCH, online=ONLINE, target=ONLINE, rows=None):
    if rows is None:
        rows = [(cpu, epoch, root, 3, va)
                for cpu in range(64) if target & (1 << cpu)]
    return struct.pack("<6Q", root, va, epoch, online, target, len(rows)) + b"".join(
        struct.pack("<5Q", *row) for row in rows)


def oracle(data: bytes) -> int:
    if len(data) < 48:
        return 1
    root, va, epoch, online, target, n = struct.unpack_from("<6Q", data)
    if not 1 <= n <= 64 or len(data) != 48 + 40 * n:
        return 1
    canonical = (va >> 48) == (0xffff if va & (1 << 47) else 0)
    if (root == 0 or root & 4095 or root >= 1 << 52 or va & 4095
            or not canonical or epoch == 0 or online == 0
            or target == 0 or target & ~online):
        return 2
    seen = 0
    for cpu, ack_epoch, ack_root, flags, ack_va in struct.iter_unpack("<5Q", data[48:]):
        if cpu >= 64 or not target & (1 << cpu) or seen & (1 << cpu):
            return 3
        if ack_epoch != epoch or ack_root != root or flags != 3 or ack_va != va:
            return 4
        seen |= 1 << cpu
    return 0 if seen == target else 5


def cases():
    base = [(0, EPOCH, ROOT, 3, VA), (5, EPOCH, ROOT, 3, VA),
            (63, EPOCH, ROOT, 3, VA)]
    yield pack()
    yield pack(rows=list(reversed(base)))
    yield pack(online=MASK, target=MASK)
    yield pack(online=1 << 63, target=1 << 63)
    high = 0xffff800000004000
    yield pack(va=high, rows=[(cpu, EPOCH, ROOT, 3, high) for cpu in (0, 5, 63)])
    yield pack(va=0x800000, rows=base)  # replay under a changed header VA
    yield pack(rows=[base[0], base[1], (63, EPOCH, ROOT, 3, VA + 4096)])
    yield pack(rows=base[:2])         # missing CPU 63
    yield pack(rows=[base[0], base[0], base[2]])
    yield pack(rows=[(64, EPOCH, ROOT, 3, VA), base[1], base[2]])
    yield pack(rows=[(0, EPOCH - 1, ROOT, 3, VA), base[1], base[2]])
    yield pack(rows=[(0, EPOCH, ROOT ^ 4096, 3, VA), base[1], base[2]])
    yield pack(rows=[(0, EPOCH, ROOT, 1, VA), base[1], base[2]])
    yield pack(root=0)
    yield pack(va=VA + 1)
    yield pack(va=1 << 48)
    yield pack(epoch=0)
    yield pack(target=0)
    yield pack(online=1, target=2)
    yield pack(rows=[])
    yield b""
    yield b"\x00" * 47
    yield pack() + b"\x00"
    rng = random.Random(SEED)
    for _ in range(2200):
        ids = sorted(rng.sample(range(64), rng.randrange(1, 65)))
        mask = sum(1 << cpu for cpu in ids)
        root = rng.randrange(1, 1 << 35) << 12
        epoch = rng.randrange(1, 1 << 64)
        va = rng.choice((0, 4096, VA, high, 0xfffffffffffff000))
        rows = [(cpu, epoch, root, 3, va) for cpu in ids]
        rng.shuffle(rows)
        yield pack(root=root, va=va, epoch=epoch, online=mask | 1,
                   target=mask, rows=rows)
    for _ in range(3200):
        ids = sorted(rng.sample(range(64), rng.randrange(2, 20)))
        mask = sum(1 << cpu for cpu in ids)
        root = rng.randrange(1, 1 << 35) << 12
        epoch = rng.randrange(1, 1 << 64)
        va = rng.choice((VA, 0x800000, high))
        rows = [(cpu, epoch, root, 3, va) for cpu in ids]
        which = rng.randrange(10)
        if which == 0:
            rows[-1] = rows[0]
        elif which == 1:
            rows[0] = (64, epoch, root, 3, va)
        elif which == 2:
            rows[0] = (ids[0], epoch ^ 1, root, 3, va)
        elif which == 3:
            rows[0] = (ids[0], epoch, root ^ 4096, 3, va)
        elif which == 4:
            rows[0] = (ids[0], epoch, root, 2, va)
        elif which == 5:
            rows[0] = (ids[0], epoch, root, 3, va ^ 4096)
        elif which == 6:
            rows = rows[:-1]
        elif which == 7:
            va ^= 4096  # header tamper without changing any per-CPU ack
        elif which == 8:
            root = 0
        else:
            mask ^= 1 << ids[-1]
        yield pack(root=root, va=va, epoch=epoch, online=mask | 1,
                   target=mask, rows=rows)


def campaign(library: Path, dishonest: bool) -> None:
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    counts = [0] * 6
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
        assert violations >= 100, ("dishonest HIA not detected", violations)
        print("dishonest HIA page-bound ack DETECTED", violations)
        return
    assert counts[0] >= 2200 and all(x > 0 for x in counts[1:]), counts
    report = {
        "schema": "heptakernel.hia-x86-shootdown-page-bound.v1",
        "status": "PASS", "cases": n, "seed": SEED, "status_counts": counts,
        "page_identity_bound": True, "hardware_ack_authenticated": False,
        "ipi_or_invlpg_emitted": False, "smp_safety_proven": False,
        "frame_reclamation_authorized": False, "full_linux_acceptance": "HOLD",
        "source_sha256": hashlib.sha256(Path("src/x86_shootdown_page_bound.hepta").read_bytes()).hexdigest(),
        "object_sha256": hashlib.sha256(Path("build/x86-shootdown-page-bound.o").read_bytes()).hexdigest(),
    }
    Path("build/x86-shootdown-page-bound-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("page-bound HIA shootdown claimed snapshot:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--dishonest", action="store_true")
    args = parser.parse_args()
    campaign(args.library, args.dishonest)
