#!/usr/bin/env python3
"""Independent x86-64 page-access oracle for native HIA admission machine code.

Inputs are *untrusted* externally supplied snapshots, not CPU measurements.
This does not install page tables, switch CR3, authenticate CPL or prove TLB/SMP.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import json
from pathlib import Path
import random
import struct

from test_x86_cr3_gate import compare_text
from test_x86_walk4_physical import fixture, oracle as walker_oracle

SUCCESS = 1 << 63
WRITE = 1 << 62
USER = 1 << 61
EXEC = 1 << 60
RESERVED = ((1 << 60) - (1 << 52))
MASK64 = (1 << 64) - 1
CR0_LONG = (1 << 31) | 1
CR0_WP = 1 << 16
CR4_PAE = 1 << 5
CR4_SMEP = 1 << 20
CR4_SMAP = 1 << 21
EFER_LONG = (1 << 8) | (1 << 10)
EFER_NXE = 1 << 11


def oracle(mapping: int, intent: int, cr0: int, cr4: int, efer: int) -> int:
    if not mapping & SUCCESS or mapping & RESERVED:
        return 1
    if intent & ~15 or intent & 6 == 6:
        return 2
    if ((cr0 & CR0_LONG) != CR0_LONG
            or not cr4 & CR4_PAE
            or (efer & EFER_LONG) != EFER_LONG
            or cr4 & ((1 << 12) | (1 << 17))):
        return 3
    is_user, writing, fetching, ac = (bool(intent & b) for b in (1, 2, 4, 8))
    mapped_user = bool(mapping & USER)
    writable = bool(mapping & WRITE)
    executable = bool(mapping & EXEC)
    # NX was observed in the walk, but NXE=0 would make that entry reserved.
    if not executable and not efer & EFER_NXE:
        return 9
    if is_user and not mapped_user:
        return 4
    if not is_user and mapped_user and cr4 & CR4_SMAP and not fetching and not ac:
        return 8
    if not is_user and mapped_user and cr4 & CR4_SMEP and fetching:
        return 7
    if writing and not writable and (is_user or cr0 & CR0_WP):
        return 5
    if fetching and not executable:
        return 6
    return 0


def campaign(library: Path, object_file: Path | None, walk_library: Path | None) -> dict:
    native = ctypes.CDLL(str(library.resolve())).x86_access_admit
    native.argtypes = [ctypes.c_uint64] * 5
    native.restype = ctypes.c_uint32
    rng = random.Random(0xACCE5511)
    result = Counter()

    def check(mapping: int, intent: int, cr0: int, cr4: int, efer: int):
        args = (mapping, intent, cr0, cr4, efer)
        expected = oracle(*args)
        actual = native(*args)
        assert expected == actual, (tuple(hex(x) for x in args), expected, actual)
        result[expected] += 1

    valid0, valid4, valide = CR0_LONG | CR0_WP, CR4_PAE, EFER_LONG | EFER_NXE
    for user_map in (0, USER):
        for write_map in (0, WRITE):
            for exec_map in (0, EXEC):
                for intent in range(32):
                    for wp in (0, CR0_WP):
                        for features in (0, CR4_SMEP, CR4_SMAP, CR4_SMEP | CR4_SMAP):
                            for nxe in (0, EFER_NXE):
                                mapping = SUCCESS | 0x301000 | user_map | write_map | exec_map
                                check(mapping, intent, CR0_LONG | wp,
                                      CR4_PAE | features, EFER_LONG | nxe)

    for _ in range(7000):
        mapping = rng.getrandbits(52) | rng.choice(
            (0, SUCCESS, SUCCESS | WRITE, SUCCESS | USER,
             SUCCESS | EXEC, SUCCESS | WRITE | USER | EXEC,
             SUCCESS | WRITE | EXEC, SUCCESS | USER | EXEC))
        if rng.randrange(11) == 0:
            mapping |= 1 << rng.randrange(52, 60)
        intent = rng.randrange(32) if rng.randrange(9) else rng.getrandbits(64)
        cr0 = rng.choice((valid0, CR0_LONG, 0, rng.getrandbits(64)))
        cr4 = rng.choice((valid4, valid4 | CR4_SMEP,
                          valid4 | CR4_SMAP, valid4 | CR4_SMEP | CR4_SMAP,
                          valid4 | (1 << 17), rng.getrandbits(64)))
        efer = rng.choice((valide, EFER_LONG, 0, rng.getrandbits(64)))
        check(mapping, intent, cr0, cr4, efer)

    for code in range(10):
        assert result[code] >= (50 if code else 300), (code, result)

    linked = 0
    if walk_library is not None:
        walker = ctypes.CDLL(str(walk_library.resolve())).f0
        walker.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        walker.restype = ctypes.c_uint32
        for mode in (12, 21, 30):
            for _ in range(60):
                va = rng.choice([0, 0x1000, 0xffff800000001000,
                                 0x7fffffffffff, rng.getrandbits(64)])
                request, pages = fixture(rng, va, mode=mode,
                                         order=rng.sample(range(4), 4))
                expectation = walker_oracle(request, pages, 16)
                req = ctypes.create_string_buffer(request)
                ram = ctypes.create_string_buffer(pages)
                out = ctypes.create_string_buffer(16)
                status = walker(req, len(request), out, 16, ram, len(pages))
                assert status == expectation[0], (status, expectation)
                if status:
                    continue
                returned_status, mapping = struct.unpack_from("<2Q", out.raw)
                assert returned_status == 0 and mapping == expectation[1]
                for intent in (0, 1, 2, 3, 4, 5, 8, 10, 12):
                    for features in (0, CR4_SMEP, CR4_SMAP, CR4_SMEP | CR4_SMAP):
                        check(mapping, intent, valid0, valid4 | features, valide)
                        linked += 1
    report = {
        "schema": "heptakernel.hia-x86-access-admission.v1",
        "status": "PASS",
        "cases": sum(result.values()),
        "status_counts": {str(i): result[i] for i in range(10)},
        "linked_physical_walker_cases": linked,
        "native_hia": True,
        "hardware_cpl_authenticated": False,
        "hardware_cr3_authenticated": False,
        "caller_supplied_cpu_state": True,
        "linux_full_acceptance": "HOLD",
    }
    if object_file:
        report["object_shared_text_sha256"] = compare_text(object_file, library)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--walk-library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        f = ctypes.CDLL(str(args.library.resolve())).x86_access_admit
        f.argtypes = [ctypes.c_uint64] * 5
        f.restype = ctypes.c_uint32
        sample = (0, 0, CR0_LONG | CR0_WP, CR4_PAE, EFER_LONG | EFER_NXE)
        assert oracle(*sample) == 1 and f(*sample) == 0
        print("Dishonest HIA unconditional access grant: REJECTED")
        return
    report = campaign(args.library, args.object, args.walk_library)
    Path("build/x86-access-gate-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Native HIA page access admission:", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
