#!/usr/bin/env python3
"""Independent byte-level oracle for bounded native HIA shootdown snapshots.

This tests claims encoded by untrusted guest/host observations, NOT actual IPIs
or safe memory reclamation. The tested .hepta source has no privilege effects.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import random
import struct
from pathlib import Path

MASK = (1 << 64) - 1
ROOT = 0x200000
VA = 0x400000
EPOCH = 37
ONLINE = (1 << 63) | (1 << 5) | 1
SEED = 0x71BCA910


def pack(*, root=ROOT, va=VA, epoch=EPOCH, online=ONLINE,
         target=ONLINE, rows=None):
    if rows is None:
        rows = [(cpu, epoch, root, 3)
                for cpu in range(64) if (target >> cpu) & 1]
    return struct.pack("<6Q", root, va, epoch, online, target, len(rows)) + b"".join(
        struct.pack("<4Q", *row) for row in rows)


def oracle(data: bytes) -> int:
    if len(data) < 48:
        return 1
    root, va, epoch, online, target, n = struct.unpack_from("<6Q", data)
    if not (1 <= n <= 64) or len(data) != 48 + 32 * n:
        return 1
    canonical = (va >> 48) == (0xffff if va & (1 << 47) else 0)
    if (root == 0 or root & 4095 or root >= (1 << 52)
            or va & 4095 or not canonical or epoch == 0
            or online == 0 or target == 0 or target & ~online):
        return 2
    seen = 0
    for cpu, seen_epoch, seen_root, completed in struct.iter_unpack("<4Q", data[48:]):
        if cpu >= 64 or not target & (1 << cpu) or seen & (1 << cpu):
            return 3
        if seen_epoch != epoch or seen_root != root or completed != 3:
            return 4
        seen |= 1 << cpu
    return 0 if seen == target else 5


def campaign(library: Path, dishonest: bool) -> dict:
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    native.restype = ctypes.c_uint32
    base_rows = [(0, EPOCH, ROOT, 3), (5, EPOCH, ROOT, 3),
                 (63, EPOCH, ROOT, 3)]
    cases = [
        pack(), pack(rows=list(reversed(base_rows))),
        pack(online=1 << 63, target=1 << 63),
        pack(online=1, target=1),
        pack(online=MASK, target=MASK),
        pack(online=MASK, target=MASK, rows=[
            (cpu, EPOCH, ROOT, 3) for cpu in reversed(range(64))]),
        b"", b"\0" * 47, pack() + b"\0", pack(rows=[]),
        pack(root=0), pack(root=4095), pack(root=1 << 52),
        pack(va=VA + 1), pack(va=1 << 48),
        pack(va=0xffff800000004000),
        pack(epoch=0), pack(online=0), pack(target=0),
        pack(online=1, target=2),
        pack(rows=base_rows[:2]),
        pack(rows=[base_rows[0], base_rows[0], base_rows[2]]),
        pack(rows=[(64, EPOCH, ROOT, 3), base_rows[1], base_rows[2]]),
        pack(rows=[(1, EPOCH, ROOT, 3), base_rows[1], base_rows[2]]),
        pack(rows=[(0, EPOCH - 1, ROOT, 3), base_rows[1], base_rows[2]]),
        pack(rows=[(0, EPOCH, ROOT ^ 0x1000, 3), base_rows[1], base_rows[2]]),
        pack(rows=[(0, EPOCH, ROOT, 1), base_rows[1], base_rows[2]]),
        pack(rows=[(0, EPOCH, ROOT, 7), base_rows[1], base_rows[2]]),
    ]
    # Both positive and adversarial sampled masks include high CPU IDs. The
    # reference oracle is byte decoding, not an invocation of the HIA compiler.
    rng = random.Random(SEED)
    for _ in range(2000):
        ids = sorted(rng.sample(range(64), rng.randrange(1, 65)))
        mask = sum(1 << cpu for cpu in ids)
        epoch = rng.randrange(1, 1 << 64)
        root = rng.randrange(1, 1 << 35) << 12
        va = rng.choice((0, 4096, VA, 0xffff800000004000,
                         0xfffffffffffff000))
        rows = [(cpu, epoch, root, 3) for cpu in ids]
        rng.shuffle(rows)
        cases.append(pack(root=root, va=va, epoch=epoch,
                          online=mask | 1, target=mask, rows=rows))
    for _ in range(4500):
        ids = sorted(rng.sample(range(64), rng.randrange(1, 11)))
        mask = sum(1 << cpu for cpu in ids)
        root = rng.randrange(1, 1 << 35) << 12
        epoch = rng.randrange(1, 1 << 64)
        rows = [(cpu, epoch, root, 3) for cpu in ids]
        fault = rng.randrange(10)
        if fault == 0:
            rows[-1] = (rows[0][0], epoch, root, 3)
        elif fault == 1:
            rows[-1] = (64, epoch, root, 3)
        elif fault == 2:
            rows[0] = (rows[0][0], epoch ^ 1, root, 3)
        elif fault == 3:
            rows[0] = (rows[0][0], epoch, root ^ 4096, 3)
        elif fault == 4:
            rows[0] = (rows[0][0], epoch, root, rng.choice((0, 1, 2, 7)))
        elif fault == 5:
            rows = rows[:-1]
        elif fault == 6:
            mask |= 1 << rng.randrange(64)
            # May remain unchanged; the reference oracle governs the result.
        elif fault == 7:
            rows[0] = (rows[0][0], epoch, root, 3)
            mask ^= 1 << rows[0][0]
        elif fault == 8:
            epoch = 0
        else:
            root += 1
        cases.append(pack(root=root, epoch=epoch, target=mask,
                          online=mask | 1, rows=rows))
    counts = [0] * 6
    violations = 0
    for raw in cases:
        expected = oracle(raw)
        source = ctypes.create_string_buffer(b"\xa7" * 32 + raw + b"\xa7" * 32)
        before = bytes(source)
        returned = native(ctypes.addressof(source) + 32, len(raw))
        if bytes(source) != before:
            raise AssertionError("native HIA modified read-only supplied ledger")
        if dishonest:
            if expected and returned == 0:
                violations += 1
            continue
        if returned != expected:
            raise AssertionError((raw.hex()[:160], expected, returned))
        counts[returned] += 1
    if dishonest:
        assert violations >= 100, "dishonest HIA always-accept negative was not detected"
        print("dishonest HIA shootdown admission DETECTED", violations)
        return {"negative_control": "DETECTED", "violations": violations}
    assert counts[0] >= 2000 and all(counts[x] > 0 for x in range(1, 6)), counts
    result = {
        "schema": "heptakernel.hia-x86-shootdown-snapshot.v1",
        "status": "PASS", "seed": SEED, "cases": len(cases),
        "status_counts": counts, "native_hia": True,
        "hardware_ack_authenticated": False,
        "ipi_or_invlpg_emitted": False, "smp_safety_proven": False,
        "frame_reclamation_authorized": False,
        "full_linux_acceptance": "HOLD",
        "source_sha256": hashlib.sha256(
            Path("src/x86_shootdown_admit.hepta").read_bytes()).hexdigest(),
        "object_sha256": hashlib.sha256(
            Path("build/x86-shootdown-admit.o").read_bytes()).hexdigest(),
    }
    Path("build/x86-shootdown-admit-report.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("native HIA claimed shootdown snapshot:", json.dumps(result, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--dishonest", action="store_true")
    args = parser.parse_args()
    campaign(args.library, args.dishonest)


if __name__ == "__main__":
    main()
