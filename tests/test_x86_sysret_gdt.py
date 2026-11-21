#!/usr/bin/env python3
"""Byte-level differential tests of the real HIA-native SYSRET GDT slot writer.

This checks one extra 0x40 ring-3 code descriptor while preserving existing
0x30/0x38 native-HIA-installed selectors. No privileged instruction is run here.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import tempfile

DATA = 58531401993093119  # fixed HIA-installed user data at offset 0x38
CODE = 49532998831374335  # HIA user long-mode code at offset 0x40
U64 = (1 << 64) - 1

def native(path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = (ctypes.c_void_p, ctypes.c_uint64,
                  ctypes.c_void_p, ctypes.c_uint64,
                  ctypes.c_void_p, ctypes.c_uint64)
    f.restype = ctypes.c_uint32
    return f

def one(f, request, table, *, malicious=False):
    r = ctypes.create_string_buffer(request, len(request) if request else 1)
    g = ctypes.create_string_buffer(table, len(table) if table else 1)
    out = ctypes.create_string_buffer(b"\xa5" * 24)
    old = bytes(g.raw[:len(table)])
    got = f(r, len(request), out, 24, g, len(table))
    after = bytes(g.raw[:len(table)])
    rep = bytes(out.raw[:16])
    guard = bytes(out.raw[16:24])
    if malicious:
        # A separately compiled HIA no-op claims success while leaving the
        # real descriptor absent: independent physical-byte oracle must see it.
        assert got == 0 and after == old and rep == b"\xa5" * 16
        assert len(request) == 16 and len(table) == 72
        assert struct.unpack_from("<Q", table, 64)[0] == 0
        return
    assert guard == b"\xa5" * 8, "reply guard mutated"
    if len(request) != 16:
        status, value, expected = 2, 0, old
    elif len(table) != 72:
        status, value, expected = 4, 0, old
    else:
        old_code, old_data = struct.unpack("<QQ", request)
        seen_code = struct.unpack_from("<Q", table, 64)[0]
        seen_data = struct.unpack_from("<Q", table, 56)[0]
        if old_code != seen_code or old_data != seen_data or seen_data != DATA:
            status, value, expected = 9, 0, old
        else:
            status, value = 0, CODE
            expected = old[:64] + struct.pack("<Q", CODE)
    assert got == status, (got, status, request.hex(), table.hex())
    assert rep == struct.pack("<QQ", status, value), (rep.hex(), status, value)
    assert after == expected, "native HIA changed unauthorized GDT bytes"

def text_identity(obj, so):
    with tempfile.TemporaryDirectory(prefix="sysret-gdt-text-") as root:
        hashes = []
        for name, source in (("object", obj), ("shared", so)):
            dest = Path(root) / name
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(source.resolve()), str(dest)],
                           check=True, capture_output=True, timeout=15)
            data = dest.read_bytes()
            assert data
            hashes.append(hashlib.sha256(data).hexdigest())
        assert hashes[0] == hashes[1]
        return hashes[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--object", type=Path)
    ap.add_argument("--expect-unsafe", action="store_true")
    args = ap.parse_args()
    f = native(args.library)
    base = bytearray(72)
    struct.pack_into("<Q", base, 56, DATA)
    request = struct.pack("<QQ", 0, DATA)
    if args.expect_unsafe:
        one(f, request, bytes(base), malicious=True)
        print("dishonest HIA SYSRET GDT no-op: DETECTED BY INDEPENDENT ORACLE")
        return
    accepted = refused = 0
    def check(rq, table):
        nonlocal accepted, refused
        one(f, rq, table)
        valid = (len(rq) == 16 and len(table) == 72 and
                 struct.unpack_from("<Q", rq, 0)[0] ==
                    struct.unpack_from("<Q", table, 64)[0] and
                 struct.unpack_from("<Q", rq, 8)[0] ==
                    struct.unpack_from("<Q", table, 56)[0] == DATA)
        accepted += int(valid)
        refused += int(not valid)
    check(request, bytes(base))
    already = bytearray(base)
    struct.pack_into("<Q", already, 64, CODE)
    check(struct.pack("<QQ", CODE, DATA), bytes(already))
    for rq in (b"", b"\0" * 8, b"\0" * 24,
               struct.pack("<QQ", 1, DATA),
               struct.pack("<QQ", 0, DATA ^ 1),
               struct.pack("<QQ", CODE, DATA)):
        check(rq, bytes(base))
    for size in (0, 1, 63, 64, 65, 71, 73, 80):
        check(request, bytes(base[:size]).ljust(size, b"\0"))
    for corrupt in (0, 1, DATA ^ 1, U64):
        malformed = bytearray(base)
        struct.pack_into("<Q", malformed, 56, corrupt)
        check(struct.pack("<QQ", 0, corrupt), bytes(malformed))
    rng = random.Random(0x6117D7)
    for _ in range(2400):
        gdt = bytearray(rng.randbytes(72))
        # Mix genuine authorized GDT with adversarial stale/forged states.
        if rng.randrange(5) != 0:
            struct.pack_into("<Q", gdt, 56, DATA)
        if rng.randrange(4) == 0:
            struct.pack_into("<Q", gdt, 64, rng.choice((0, CODE, U64)))
        actual_old = struct.unpack_from("<Q", gdt, 64)[0]
        actual_data = struct.unpack_from("<Q", gdt, 56)[0]
        req_old = actual_old if rng.randrange(3) else actual_old ^ 1
        req_data = actual_data if rng.randrange(3) else actual_data ^ 1
        check(struct.pack("<QQ", req_old, req_data), bytes(gdt))
    assert accepted >= 250 and refused >= 1600, (accepted, refused)
    report = {"schema": "heptakernel.hia-sysret-gdt.v1", "status": "PASS",
              "accepted": accepted, "refused": refused, "cases": accepted + refused,
              "native_hia": True, "gdt_code_slot": 64, "gdt_data_slot": 56,
              "sysretq_executed_here": False, "smp_atomic": False,
              "linux_full_acceptance": "HOLD",
              "source_sha256": hashlib.sha256(Path("src/x86_sysret_gdt.hepta").read_bytes()).hexdigest()}
    if args.object:
        report["object_shared_text_sha256"] = text_identity(args.object, args.library)
    Path("build/x86-sysret-gdt-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Native HIA SYSRET GDT descriptor:", json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
