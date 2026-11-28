#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the composed HIA stat staging entry against the pinned layout."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import struct
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("devnum_oracle", HERE / "test_linux_devnum.py")
devnum = importlib.util.module_from_spec(spec)
spec.loader.exec_module(devnum)
require, digest, run = devnum.require, devnum.digest, devnum.run
STAT = ROOT / "src/x86_stat_dev_fields.hepta"
HEADERS = {
    **devnum.HEADERS,
    "arch/x86/include/uapi/asm/stat.h": "9e3982d95d0f18ebaceb38795a326778310c946f",
    "arch/x86/include/uapi/asm/posix_types.h": "c661e95f0134dbedab539462c1d620e2071a8e5b",
    "arch/x86/include/uapi/asm/posix_types_64.h": "515afb8059ce359f9deef21dba95003fc11e2781",
    "arch/x86/include/uapi/asm/bitsperlong.h": "5d72c84588388793d0d54a21b8252c48af3347d6",
    "include/uapi/asm-generic/posix_types.h": "0a90ad92dbf3a29df42901afeb643feeddbe87ae",
    "include/uapi/asm-generic/bitsperlong.h": "fadb3f857f2855db40dca88333d977e6a51b4c11",
}
C_ORACLE = r"""
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <asm/stat.h>
#define __KERNEL__
#ifndef __always_inline
#define __always_inline inline
#endif
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint32_t dev_t;
typedef uint64_t u64;
#include "linux/kdev_t.h"

_Static_assert(sizeof(struct stat) == 144, "x86-64 native stat record size");
_Static_assert(offsetof(struct stat, st_dev) == 0, "native st_dev");
_Static_assert(offsetof(struct stat, st_rdev) == 40, "native st_rdev");
_Static_assert(sizeof(((struct stat *)0)->st_dev) == 8, "st_dev width");
_Static_assert(sizeof(((struct stat *)0)->st_rdev) == 8, "st_rdev width");

u32 reference(const void *req, u64 req_len, void *out, u64 out_len) {
    if (req_len != 16 || out_len != sizeof(struct stat)) return 1;
    u64 inputs[2];
    memcpy(inputs, req, sizeof(inputs));
    if (inputs[0] > UINT32_MAX || inputs[1] > UINT32_MAX) return 2;
    struct stat words;
    words.st_dev = new_encode_dev((dev_t)inputs[0]);
    words.st_rdev = new_encode_dev((dev_t)inputs[1]);
    memcpy((char *)out + offsetof(struct stat, st_dev), &words.st_dev, sizeof(words.st_dev));
    memcpy((char *)out + offsetof(struct stat, st_rdev), &words.st_rdev, sizeof(words.st_rdev));
    return 0;
}
"""


def compose():
    codec = devnum.SOURCE.read_bytes()
    header, export, body = codec.split(b"\n", 2)
    require(header == b"hia-asm.v1 hepta.hia.program.v8 selfhost_elf"
            and export == b"exports(linux_devnum)" and body.startswith(b"fn linux_devnum("),
            "codec module prefix changed")
    piece = STAT.read_bytes()
    require(piece.startswith(header + b"\nfn x86_stat_dev_fields(") and piece.endswith(b"end\n"),
            "stat entry prefix or terminator changed")
    return piece + body


def wrap(path, symbol):
    f = getattr(ctypes.CDLL(str(path)), symbol)
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * (3 if symbol == "f0" else 2)
    f.restype = ctypes.c_uint32
    return f


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--compiler", type=Path, required=True)
    p.add_argument("--linux-root", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--composed", type=Path, help="save exact composed HIA source for verification")
    args = p.parse_args()
    compiler = args.compiler.resolve()
    root = args.linux_root.resolve()
    require(digest(compiler.read_bytes()) == devnum.COMPILER, "compiler fingerprint mismatch")
    for path, expected in HEADERS.items():
        data = (root / path).read_bytes()
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        require(blob == expected, f"upstream Git blob mismatch: {path}")

    source = compose()
    rng = random.Random(628151)
    accepted = refused = 0
    with tempfile.TemporaryDirectory(prefix="hia-stat-device-") as tmp:
        folder = Path(tmp)
        native_path, obj_sha, text_sha = devnum.native_image(folder, compiler, source, "stat", "f0")
        c_so = folder / "reference.so"
        run("cc", "-x", "c", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
            "-I", str(root / "include"), "-I", str(root / "include/uapi"),
            "-I", str(root / "arch/x86/include/uapi"), "-o", str(c_so), "-", input=C_ORACLE.encode())
        actual, oracle = wrap(native_path, "f0"), wrap(c_so, "reference")
        test_offsets = ((0, 8), (40, 48))

        def check(dev, rdev, nreq=16, ndst=144, unaligned=0):
            nonlocal accepted, refused
            input_data = struct.pack("<QQ", dev, rdev)
            request = ctypes.create_string_buffer(input_data, 16)
            prefix = 16 + unaligned
            baseline = rng.randbytes(prefix + 144 + 16)
            hia = ctypes.create_string_buffer(baseline, len(baseline))
            c = ctypes.create_string_buffer(baseline, len(baseline))
            scratch = ctypes.create_string_buffer(b"unchanged-work")
            scratch_before = scratch.raw
            ans = actual(request, nreq, ctypes.byref(hia, prefix), ndst, scratch, 0)
            expected = oracle(request, nreq, ctypes.byref(c, prefix), ndst)
            require((ans, hia.raw) == (expected, c.raw), "native status or full bytes mismatch")
            require(request.raw == input_data and scratch.raw == scratch_before, "read-only argument modified")
            if ans:
                refused += 1
                require(hia.raw == baseline, "refusal path changed staging")
            else:
                accepted += 1
                writable = {prefix + i for start, stop in test_offsets for i in range(start, stop)}
                require(all(hia.raw[i] == byte for i, byte in enumerate(baseline) if i not in writable),
                        "changed non-device bytes or canary")

        values = [0, 1, 0xff, 0x100, 0xfffff, 0x100000, 0xffffffff]
        values += [1 << i for i in range(32)]
        for dev in values:
            for rdev in values:
                check(dev, rdev, unaligned=(dev ^ rdev) % 8)
        for i in range(4096):
            check(rng.getrandbits(32), rng.getrandbits(32), unaligned=i % 8)
        for invalid in (1 << 32, (1 << 32) | 255, 1 << 63, devnum.REFUSED):
            for good in (0, 0xffffffff):
                check(invalid, good)
                check(good, invalid)
            check(invalid, invalid)
        for nreq in (0, 1, 15, 17, devnum.REFUSED):
            check(1, 2, nreq=nreq)
        for ndst in (0, 1, 8, 40, 47, 143, 145, devnum.REFUSED):
            check(1, 2, ndst=ndst)

        # Deliberate local fixture: incorrect output field offset must disagree.
        anchor = b'offset_r:usize = const() {"value":40}'
        require(source.count(anchor) == 1, "mutation anchor not unique")
        mutant = source.replace(anchor, b'offset_r:usize = const() {"value":48}', 1)
        mutant_path, _, mutant_sha = devnum.native_image(folder, compiler, mutant, "wrong_offset", "f0")
        changed = wrap(mutant_path, "f0")
        inputs = ctypes.create_string_buffer(struct.pack("<QQ", 1, 0x100), 16)
        got, want = ctypes.create_string_buffer(144), ctypes.create_string_buffer(144)
        require(oracle(inputs, 16, want, 144) == changed(inputs, 16, got, 144, None, 0) == 0
                and got.raw != want.raw and mutant_sha != text_sha, "wrong offset undetected")

    report = {
        "schema": "heptakernel.x86-stat-device-fields.v1",
        "status": "PASS",
        "full_linux_acceptance": "HOLD",
        "linux_commit": devnum.LINUX,
        "linux_header_git_blobs": HEADERS,
        "compiler_sha256": devnum.COMPILER,
        "field_stager_sha256": digest(STAT.read_bytes()),
        "standalone_codec_sha256": digest(devnum.SOURCE.read_bytes()),
        "composed_hia_sha256": digest(source),
        "native_object_sha256": obj_sha,
        "loaded_text_sha256": text_sha,
        "wrong_offset_control_text_sha256": mutant_sha,
        "accepted": accepted,
        "refused_without_write": refused,
        "all_other_bytes_and_canaries_unchanged": True,
        "native_negative_control_detected": True,
    }
    if args.composed:
        args.composed.write_bytes(source)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {accepted} staged records, {refused} unchanged refusals; report {args.report}")


if __name__ == "__main__":
    main()
