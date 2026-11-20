#!/usr/bin/env python3
"""Independent byte-level oracle for one 4 KiB HIA ELF file/BSS page fill.

This is a single-owner materialization primitive, NOT an ELF loader, process,
page-table operation, dynamic linker or Linux execve implementation.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import random
import struct
import subprocess
import tempfile
from pathlib import Path

PAGE = 4096
HEADER = 40
RECEIPT = 16
CAP_MEM = 1 << 32
CAP_INDEX = (1 << 20) - 1
STAMP = bytes([165]) + bytes(15)


def reference(envelope: bytes, receipt: bytes, page: bytes):
    if len(envelope) < HEADER:
        return 1, receipt, page
    if len(receipt) != RECEIPT:
        return 2, receipt, page
    if len(page) != PAGE:
        return 3, receipt, page
    file_offset, file_size, mem_size, lead, page_index = struct.unpack_from(
        "<5Q", envelope, 0)
    if (not mem_size or file_size > mem_size or lead >= PAGE
            or mem_size > CAP_MEM or page_index > CAP_INDEX):
        return 4, receipt, page
    contents = envelope[HEADER:]
    if file_offset > len(contents) or file_size > len(contents) - file_offset:
        return 5, receipt, page
    if page_index * PAGE >= lead + mem_size:
        return 6, receipt, page
    output = bytearray(PAGE)
    # Oracle is defined as virtual-memory byte projection, not a copy of the
    # HIA branch and range logic. Pages outside file bytes remain BSS zeroes.
    source = contents[file_offset:file_offset + file_size]
    base = page_index * PAGE
    for position in range(PAGE):
        relative = base + position - lead
        if 0 <= relative < len(source):
            output[position] = source[relative]
    return 0, STAMP, bytes(output)


def envelope(fields: tuple[int, int, int, int, int], contents: bytes):
    return struct.pack("<5Q", *fields) + contents


def native_function(path: Path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32
    return f


def campaign(path: Path, unsafe: bool = False) -> dict:
    rng = random.Random(0x48494120261120)
    function = native_function(path)
    counts: dict[int, int] = {}
    cases = accepted = divergences = 0

    def check(request: bytes, *, reply_size: int = RECEIPT,
              page_size: int = PAGE):
        nonlocal cases, accepted, divergences
        # Each real input and output has separate red zones. Record every
        # complete backing buffer before the HIA native function is invoked.
        initial_reply = rng.randbytes(reply_size)
        initial_page = rng.randbytes(page_size)
        src = ctypes.create_string_buffer(bytes([0xA7]) * 32 + request
                                          + bytes([0xA7]) * 32)
        rec = ctypes.create_string_buffer(bytes([0xB8]) * 32 + initial_reply
                                          + bytes([0xB8]) * 32)
        dst = ctypes.create_string_buffer(bytes([0xC9]) * 32 + initial_page
                                          + bytes([0xC9]) * 32)
        src_before, rec_before, dst_before = bytes(src), bytes(rec), bytes(dst)
        expected, expected_rec, expected_page = reference(
            request, initial_reply, initial_page)
        actual = function(ctypes.addressof(src) + 32, len(request),
                          ctypes.addressof(rec) + 32, reply_size,
                          ctypes.addressof(dst) + 32, page_size)
        observed_rec = bytes(rec)[32:32 + reply_size]
        observed_page = bytes(dst)[32:32 + page_size]
        cases += 1
        accepted += expected == 0
        counts[expected] = counts.get(expected, 0) + 1
        mismatch = (expected != actual or expected_rec != observed_rec
                    or expected_page != observed_page)
        divergences += mismatch
        if not unsafe:
            assert not mismatch, (
                "HIA-native versus independent oracle", cases,
                expected, actual, expected_rec[:16].hex(),
                observed_rec[:16].hex())
        assert bytes(src) == src_before, ("source modified", cases)
        assert (bytes(rec)[:32] == rec_before[:32]
                and bytes(rec)[32 + reply_size:] == rec_before[32 + reply_size:]), (
                    "receipt canary modified", cases)
        assert (bytes(dst)[:32] == dst_before[:32]
                and bytes(dst)[32 + page_size:] == dst_before[32 + page_size:]), (
                    "page canary modified", cases)

    for lead in (0, 1, 4095):
        for file_size, mem_size in ((0, 1), (1, 1), (1, 8192),
                                    (4096, 4096), (4096, 8193),
                                    (8193, 16384)):
            for file_offset in (0, 7, 64):
                payload = rng.randbytes(file_offset + file_size)
                for page_index in range(min(5, (lead + mem_size + PAGE - 1)
                                            // PAGE)):
                    check(envelope((file_offset, file_size, mem_size,
                                    lead, page_index), payload))

    # Exact rejection at every field boundary, including u64 overflow attempts.
    base = (16, 64, 9000, 31, 0)
    payload = rng.randbytes(256)
    for short in range(40):
        check(envelope(base, payload)[:short])
    for field_index in range(5):
        for value in (0, 1, 15, 4095, 4096, CAP_INDEX,
                      CAP_MEM, (1 << 63), (1 << 64) - 1):
            fields = list(base)
            fields[field_index] = value
            check(envelope(tuple(fields), payload))
    for reply_size in (0, 1, 15, 17, 128):
        check(envelope(base, payload), reply_size=reply_size)
    for page_size in (0, 1, 4095, 4097, 8192):
        check(envelope(base, payload), page_size=page_size)

    for _ in range(1000):
        lead = rng.randrange(PAGE)
        mem_size = rng.randrange(1, 131073)
        file_size = rng.randrange(mem_size + 1)
        offset = rng.randrange(0, 129)
        payload = rng.randbytes(offset + file_size)
        max_index = (lead + mem_size - 1) // PAGE
        index = rng.randrange(max_index + 1)
        check(envelope((offset, file_size, mem_size, lead, index), payload))

    # Hostile field and payload-length changes, with multiple independent
    # mutations and with valid bytes preserved wherever possible.
    for _ in range(450):
        lead = rng.randrange(PAGE)
        mem_size = rng.randrange(1, 33000)
        file_size = rng.randrange(mem_size + 1)
        offset = rng.randrange(0, 64)
        contents = rng.randbytes(offset + file_size)
        fields = [offset, file_size, mem_size, lead,
                  rng.randrange((lead + mem_size - 1) // PAGE + 1)]
        kind = rng.randrange(7)
        if kind == 0:
            fields[0] = len(contents) + 1
        elif kind == 1:
            fields[1] = mem_size + 1
        elif kind == 2:
            fields[2] = 0
        elif kind == 3:
            fields[3] = PAGE
        elif kind == 4:
            fields[4] = (lead + mem_size + PAGE - 1) // PAGE
        elif kind == 5:
            fields[4] = (1 << 64) - 1
        else:
            fields[2] = CAP_MEM + 1
        check(envelope(tuple(fields), contents))

    if unsafe:
        assert divergences >= 500, (divergences, cases)
    else:
        assert divergences == 0 and accepted > 1000, (divergences, accepted)
    return {
        "schema": "heptakernel.hia-elf64-page-fill.v1",
        "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
        "cases": cases, "accepted": accepted,
        "status_counts": counts, "divergences": divergences,
        "native_hia": True, "single_owner_only": True,
        "actual_elf_loader": False, "full_linux_acceptance": "HOLD",
    }


def text_hash(obj: Path, library: Path):
    with tempfile.TemporaryDirectory() as tmp:
        texts = []
        for index, file in enumerate((obj, library)):
            path = Path(tmp) / str(index)
            subprocess.run(["objcopy", "--only-section=.text", "-O", "binary",
                            str(file.resolve()), str(path)], check=True)
            texts.append(path.read_bytes())
        assert texts[0] and texts[0] == texts[1]
        return hashlib.sha256(texts[0]).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    result = campaign(args.library, unsafe=args.expect_unsafe)
    if args.object and not args.expect_unsafe:
        result["object_shared_text_sha256"] = text_hash(
            args.object, args.library)
    print(json.dumps(result, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/elf64-page-fill-report.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
