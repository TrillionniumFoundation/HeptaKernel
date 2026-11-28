#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Host differential test of a freestanding native HIA leaf against Linux."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/linux_devnum.hepta"
COMPILER = "87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54"
LINUX = "7595a62d45ee1a2297eafa5f2ef5d0a45142d84d"
HEADERS = {
    "include/linux/kdev_t.h": "4856706fbfeb4537a67e40cb54887584045a474f",
    "include/uapi/linux/kdev_t.h": "e1990f2e97772a8bb798ac9b9a9d2fd3e8790e88",
}
REFUSED = (1 << 64) - 1
ORACLE = r"""
#include <stdbool.h>
#include <stdint.h>
#define __KERNEL__
#ifndef __always_inline
#define __always_inline inline
#endif
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint32_t dev_t;
typedef uint64_t u64;
#include "linux/kdev_t.h"
u64 reference(u64 op, u64 raw) {
    if (raw > UINT32_MAX) return UINT64_MAX;
    switch (op) {
    case 0: return new_encode_dev((dev_t)raw);
    case 1: return new_decode_dev((u32)raw);
    case 2: return old_valid_dev((dev_t)raw) ? old_encode_dev((dev_t)raw) : UINT64_MAX;
    case 3: return raw <= UINT16_MAX ? old_decode_dev((u16)raw) : UINT64_MAX;
    default: return UINT64_MAX;
    }
}
"""


def require(condition, why):
    if not condition:
        raise SystemExit(why)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(*args, input=None):
    return subprocess.run(args, input=input, capture_output=True, check=True).stdout


def dump_text(binary, destination):
    run("objcopy", "--dump-section", f".text={destination}", str(binary), str(destination) + ".copy")
    return destination.read_bytes()


def native_image(folder, compiler, source, name):
    obj = folder / f"{name}.o"
    so = folder / f"{name}.so"
    object_bytes = run(str(compiler), input=source)
    require(object_bytes and object_bytes == run(str(compiler), input=source),
            "native object generation not deterministic")
    obj.write_bytes(object_bytes)
    require(not run("nm", "-u", str(obj)).strip(), "undefined target symbol")
    require("linux_devnum" in run("nm", "-g", "--defined-only", str(obj)).decode(),
            "missing exported leaf")
    run("ld", "-shared", "-z", "noexecstack", "-o", str(so), str(obj))
    require(not run("nm", "-D", "-u", str(so)).strip(), "unexpected dynamic dependency")
    raw = dump_text(obj, folder / f"{name}.obj.text")
    require(raw and raw == dump_text(so, folder / f"{name}.so.text"),
            "loaded text differs from native emitted text")
    return so, digest(object_bytes), digest(raw)


def function(path, symbol):
    f = getattr(ctypes.CDLL(str(path)), symbol)
    f.argtypes = (ctypes.c_uint64, ctypes.c_uint64)
    f.restype = ctypes.c_uint64
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", type=Path, required=True)
    ap.add_argument("--linux-root", type=Path, required=True, help="pinned Linux include tree")
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    root = args.linux_root.resolve()
    compiler = args.compiler.resolve()
    require(digest(compiler.read_bytes()) == COMPILER, "compiler fingerprint mismatch")
    for path, expected in HEADERS.items():
        data = (root / path).read_bytes()
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        require(blob == expected, f"upstream Git blob mismatch: {path}")

    counts = [0] * 5
    source = SOURCE.read_bytes()
    with tempfile.TemporaryDirectory(prefix="hia-linux-devnum-") as work:
        folder = Path(work)
        native, object_sha, text_sha = native_image(folder, compiler, source, "native")
        so = folder / "reference.so"
        run("cc", "-x", "c", "-std=c11", "-O2", "-fPIC", "-shared", "-I",
            str(root / "include"), "-o", str(so), "-", input=ORACLE.encode())
        actual, oracle = function(native, "linux_devnum"), function(so, "reference")

        def check(op, value):
            expected, got = oracle(op, value), actual(op, value)
            require(got == expected, f"op={op} value={value:#x} got={got:#x} expected={expected:#x}")
            counts[min(op, 4)] += 1
            return got

        for raw in range(1 << 16):
            dev = check(3, raw)
            require(check(2, dev) == raw, f"legacy roundtrip failed: {raw}")
        rng = random.Random(625674)
        field_edges = {0, 1, 0xff, 0x100, 0x101, 0xffe, 0xfff}
        minor_edges = field_edges | {0xffff, 0x10000, 0xffffe, 0xfffff}
        edges = {(a << 20) | b for a in field_edges for b in minor_edges}
        edges |= {0, 0xffffffff} | {1 << i for i in range(32)}
        modern = sorted(edges) + [rng.getrandbits(32) for _ in range(20000)]
        for raw in modern:
            require(check(1, check(0, raw)) == raw, "new internal roundtrip")
            require(check(0, check(1, raw)) == raw, "new packed roundtrip")
            check(2, raw)
            check(3, raw)
        for op in range(4):
            for raw in (1 << 32, (1 << 32) | 0xffff, 1 << 63, REFUSED):
                require(check(op, raw) == REFUSED, "wide operand admitted")
        for op in (4, 255, 1 << 32, REFUSED):
            for raw in (0, 1, 0xffffffff):
                require(check(op, raw) == REFUSED, "unknown operation admitted")

        needle = b'1048320}'
        require(source.count(needle) == 2, "control source shape changed")
        altered = source.replace(needle, b'1048064}', 1)
        control, _, mutant_text_sha = native_image(folder, compiler, altered, "negative")
        negative = function(control, "linux_devnum")
        require(oracle(0, 0x100) == 0x100000 and actual(0, 0x100) == 0x100000
                and negative(0, 0x100) != 0x100000 and mutant_text_sha != text_sha,
                "oracle did not detect loss of first high minor bit")

    report = {
        "schema": "heptakernel.linux-devnum-native.v1",
        "scope": "native x86-64 modern and legacy device-number conversion leaf",
        "status": "PASS",
        "full_linux_acceptance": "HOLD",
        "compiler_sha256": COMPILER,
        "linux_commit": LINUX,
        "linux_header_git_blobs": HEADERS,
        "source_sha256": digest(source),
        "object_sha256": object_sha,
        "text_sha256": text_sha,
        "mutant_text_sha256": mutant_text_sha,
        "calls_by_op_0_1_2_3_and_unknown": counts,
        "differential_calls": sum(counts),
        "legacy_packed_values_exhaustively_tested": 65536,
        "modern_samples_per_roundtrip_direction": len(modern),
        "native_negative_control_detected": True,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {sum(counts)} native/oracle calls; report {args.report}")


if __name__ == "__main__":
    main()
