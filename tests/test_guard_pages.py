#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Probe the actual HIA FFI using hardware guard pages in an isolated process.

The tests concern the single-arena allocator component. They do not establish
Linux compatibility, general kernel memory safety, or arbitrary FFI-pointer
validity. The caller supplies valid, disjoint, exclusively owned capabilities.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import mmap
from pathlib import Path
import struct
import subprocess
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(library):
    page = mmap.PAGESIZE
    loaded = ctypes.CDLL(str(library.resolve()))
    entry = loaded.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint32
    oslib = ctypes.CDLL(None, use_errno=True)
    oslib.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    oslib.mprotect.restype = ctypes.c_int

    class Guarded:
        def __init__(self, size, initial=None, readonly=False):
            assert 0 <= size <= page
            self.size = size
            self.mapping = mmap.mmap(-1, 3 * page, prot=mmap.PROT_READ | mmap.PROT_WRITE)
            self.base = ctypes.addressof(ctypes.c_char.from_buffer(self.mapping))
            for offset in (0, 2 * page):
                assert oslib.mprotect(self.base + offset, page, 0) == 0, ctypes.get_errno()
            # Buffer end is immediately followed by PROT_NONE. For size=0 the
            # pointer itself is inaccessible, so an accidental read/write faults.
            self.ptr = self.base + 2 * page - size
            if size:
                ctypes.memset(self.ptr, 0, size)
            if initial is not None:
                assert len(initial) == size
                if size:
                    ctypes.memmove(self.ptr, initial, size)
            if readonly:
                assert oslib.mprotect(self.base + page, page, mmap.PROT_READ) == 0

        def snapshot(self):
            return ctypes.string_at(self.ptr, self.size) if self.size else b""

    calls = 0

    def call(state, command, expected, request_size=32, reply_size=16):
        nonlocal calls
        raw = struct.pack("<4Q", *command) if request_size == 32 else bytes(request_size)
        request = Guarded(request_size, raw, readonly=True)
        reply = Guarded(reply_size, bytes([0xA7]) * reply_size)
        before_request, before_state = request.snapshot(), state.snapshot()
        returned = entry(request.ptr, request.size, reply.ptr, reply.size, state.ptr, state.size)
        assert request.snapshot() == before_request
        if reply_size < 16:
            assert (returned, 0) == expected
            assert reply.snapshot() == bytes([0xA7]) * reply_size
        else:
            result = struct.unpack_from("<2Q", reply.snapshot())
            assert returned == result[0], ("return/reply mismatch", returned, result)
            assert result == expected, (command, result, expected)
        if expected[0] != 0 or command[0] == 3:
            assert state.snapshot() == before_state, (command, "unexpected state mutation")
        calls += 1

    state = Guarded(67)  # exact metadata capacity for 17 pages
    for command, expected in (
        ((0, 17, 0x503000, 2), (0, 15)),
        ((1, 8, 0, 0), (0, 0x508000)),
        ((3, 0, 0, 0), (0, 14)),
        ((2, 0x503000, 0, 0), (8, 0)),
        ((2, 0x508000, 0, 0), (0, 0)),
        ((2, 0x508000, 0, 0), (7, 0)),
        ((1, 3, 0, 0), (6, 0)),
        ((3, 1, 0, 0), (6, 0)),
        ((99, 0, 0, 0), (3, 0)),
        ((4, 2, 3, 0), (6, 0)),
        ((4, 20, 1, 0), (5, 0)),
        ((4, 2, 4, 0), (0, 0x508000)),
    ):
        call(state, command, expected)
    for size in (0, 1, 7, 15, 31, 33):
        call(state, (0, 0, 0, 0), (2, 0), request_size=size)
    for size in (0, 1, 7, 15):
        call(state, (0, 17, 0x503000, 0), (1, 0), reply_size=size)

    zero = Guarded(65)
    for command, expected in (
        ((0, 1, 0, 0), (0, 1)), ((1, 1, 0, 0), (0, 0)),
        ((1, 1, 0, 0), (5, 0)), ((2, 0, 0, 0), (0, 0)),
        ((2, 0, 0, 0), (7, 0)),
    ):
        call(zero, command, expected)

    for size in (0, 1, 31, 63, 64, 65, 66):
        short = Guarded(size)
        for command, expected in (
            ((0, 17, 0x400000, 0), (4, 0)),
            ((3, 0, 0, 0), (4, 0)),
            ((1, 0, 0, 0), (6, 0)),
            ((2, 1, 0, 0), (6, 0)),
            ((3, 1, 0, 0), (6, 0)),
        ):
            call(short, command, expected)
    absent = Guarded(0)
    call(absent, (0, 0, 0, 0), (1, 0), request_size=0, reply_size=0)
    call(absent, (0, 0, 0, 0), (2, 0), request_size=0)
    assert calls == 64
    return {"status": "PASS", "calls": calls,
            "tested_library_sha256": digest(library)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path, nargs="?", default=Path("build/kernel-host.so"))
    parser.add_argument("--report", type=Path, default=Path("build/guard-pages-report.json"))
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    library = args.library.resolve()
    if args.worker:
        print(json.dumps(probe(library), sort_keys=True))
        return 0

    report = {
        "schema": "heptakernel.guard-page-tests.v1",
        "scope": "Single-arena HIA allocator with exact-size host FFI capabilities",
        "tested_library": str(library), "status": "FAIL", "calls": 0,
        "linux_compatibility_tested": False, "formal_proof": False,
        "cases": [
            "Read-only request storage and inaccessible page immediately after each buffer",
            "Zero-length state/request/reply pointers into PROT_NONE",
            "Exact 67-byte metadata and short capacities 0,1,31,63,64,65,66",
            "Physical alignment with a base that is not eight-page aligned",
            "Physical address zero success distinguished from exhaustion by status",
            "Reserved prefix, double free, malformed sizes and invalid arguments",
            "Failed requests and successful count queries leave state unchanged",
            "Contiguous run allocation respects physical alignment and exact metadata guard",
        ],
    }
    try:
        report["tested_library_sha256"] = digest(library)
        command = [sys.executable, str(Path(__file__).resolve()), str(library), "--worker"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        report.update(worker_returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        if result.returncode != 0:
            raise RuntimeError("guard-page worker failed or faulted")
        worker = json.loads(result.stdout)
        if worker.get("status") != "PASS" or worker.get("calls") != 64:
            raise RuntimeError("worker did not report the complete fixed campaign")
        if worker.get("tested_library_sha256") != report["tested_library_sha256"]:
            raise RuntimeError("tested library changed during the campaign")
        report.update(status="PASS", calls=64)
    except Exception as exc:
        report["error"] = repr(exc)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

