#!/usr/bin/env python3
"""Independent byte-oriented oracle for HIA native PML4 root validation.

This validates a caller-provided 4 KiB page, not CR3 or RAM provenance.
No compiler implementation, HIA interpreter, or host Linux kernel is used.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import mmap
from pathlib import Path
import random
import struct
from test_arena_router import object_text

SIZE = 4096
LIMIT = 1 << 52
ADDRESS = LIMIT - SIZE
HIGH = 0x7ff0000000000000
MASK = (1 << 64) - 1


def oracle(request: bytes, root: bytes, reply_length: int):
    if reply_length < 16:
        return 1, None
    if len(request) != 24:
        return 2, 0
    if len(root) != SIZE:
        return 4, 0
    cr3, bits, required = struct.unpack("<3Q", request)
    if not (32 <= bits <= 52 and required < 512):
        return 6, 0
    if cr3 & 4095 & ~24 or cr3 & ADDRESS == 0 or cr3 >= 1 << bits:
        return 6, 0
    present = 0
    required_present = False
    for index in range(512):
        entry, = struct.unpack_from("<Q", root, index * 8)
        if not entry & 1:
            continue
        frame = entry & ADDRESS
        # Restricted root profile: no PML4 PS, upper software/reserved bits,
        # zero table pointer or frame outside the declared physical width.
        if (entry & HIGH or entry & 128 or frame == 0
                or frame >= 1 << bits):
            return 7, 0
        present += 1
        required_present |= index == required
    return (0, present) if required_present else (5, 0)


def make_root(entries: dict[int, int]) -> bytes:
    root = bytearray(SIZE)
    for idx, entry in entries.items():
        struct.pack_into("<Q", root, idx * 8, entry)
    return bytes(root)


def make_request(cr3=0x1000, bits=48, required=0) -> bytes:
    return struct.pack("<3Q", cr3, bits, required)


def cases():
    valid = make_root({0: 0x2003, 511: 0x3003})
    fixed = [
        (make_request(), valid, 16),
        (make_request(required=511), valid, 16),
        (make_request(required=1), valid, 16),
        (make_request(), make_root({}), 16),
        (make_request(), make_root({0: 0x80}), 16),  # non-present garbage
        (make_request(), make_root({0: 0x2083}), 16),  # PML4 PS
        (make_request(), make_root({0: 0x2003 | (1 << 60)}), 16),
        (make_request(), make_root({0: 0x2003 | (1 << 63)}), 16),
        (make_request(), make_root({0: (1 << 48) | 3}), 16),
        (make_request(bits=32), make_root({0: (1 << 32) | 3}), 16),
        (make_request(), make_root({0: 1}), 16),
        (make_request(cr3=0), valid, 16),
        (make_request(cr3=0x1001), valid, 16),
        (make_request(cr3=0x1018), valid, 16),
        (make_request(cr3=0x1010), valid, 16),
        (make_request(cr3=1 << 48, bits=48), valid, 16),
        (make_request(bits=31), valid, 16),
        (make_request(bits=53), valid, 16),
        (make_request(required=512), valid, 16),
        (make_request()[:-1], valid, 16),
        (make_request() + b"\0", valid, 16),
        (make_request(), valid[:-1], 16),
        (make_request(), valid + b"\0", 16),
        (make_request(), valid, 15),
        (make_request(), valid, 0),
        (make_request(), valid, 24),
    ]
    rng = random.Random(0xC3A520261119)
    widths = (32, 36, 40, 48, 52)
    for _ in range(1300):
        bits = rng.choice(widths)
        target = rng.randrange(512)
        entries = {}
        present_count = rng.randrange(1, 9)
        for _ in range(present_count):
            index = rng.randrange(512)
            frame = (rng.randrange(1, 1 << min(bits - 12, 24)) * SIZE)
            flags = rng.choice((0x3, 0x7, 0x63, 0x103, 0x8000000000000003))
            entries[index] = frame | flags
        if rng.randrange(2):
            entries[target] = 0x2003
        if rng.randrange(7) == 0:
            entries[rng.choice(list(entries))] |= rng.choice((0x80, 1 << 60, 1 << 52))
        root = make_root(entries)
        cr3 = rng.choice((0x1000, 0x1018, 0x1001, 0, (1 << bits)))
        req = make_request(cr3=cr3, bits=bits, required=target)
        fixed.append((req, root, rng.choice((16, 16, 24))))
    return fixed



def readonly_root_page(library):
    """The original HIA object must accept an OS-enforced read-only root page."""
    if mmap.PAGESIZE != SIZE:
        raise AssertionError("x86-64 4KiB page ABI expected")
    root = make_root({0: 0x2003, 511: 0x3003})
    request = make_request()
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    libc.mprotect.restype = ctypes.c_int
    page = mmap.mmap(-1, SIZE, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                     prot=mmap.PROT_READ | mmap.PROT_WRITE)
    pointer = ctypes.addressof(ctypes.c_char.from_buffer(page))
    try:
        page[:] = root
        if libc.mprotect(pointer, SIZE, mmap.PROT_READ) != 0:
            raise OSError(ctypes.get_errno(), "mprotect(PROT_READ) failed")
        req = ctypes.create_string_buffer(request)
        reply = ctypes.create_string_buffer(b"\xbc" * 16)
        status = native(req, len(request), reply, 16, pointer, SIZE)
        assert (status, struct.unpack_from("<2Q", reply.raw)) == (0, (0, 2))
        assert page[:] == root, "native HIA modified read-only PML4"
    finally:
        if libc.mprotect(pointer, SIZE, mmap.PROT_READ | mmap.PROT_WRITE) != 0:
            raise OSError(ctypes.get_errno(), "mprotect(restore) failed")
        page.close()


def run(library, corpus):
    native = ctypes.CDLL(str(library.resolve())).f0
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint32
    counts = {}
    for n, (request, root, reply_length) in enumerate(corpus):
        source = ctypes.create_string_buffer(b"\xa5" * 32 + request + b"\xa5" * 32)
        page = ctypes.create_string_buffer(b"\xc9" * 32 + root + b"\xc9" * 32)
        output = ctypes.create_string_buffer(b"\xb8" * (reply_length + 64))
        old_source, old_page = bytes(source), bytes(page)
        expected, value = oracle(request, root, reply_length)
        status = native(ctypes.addressof(source) + 32, len(request),
                        ctypes.addressof(output) + 32, reply_length,
                        ctypes.addressof(page) + 32, len(root))
        assert status == expected, (n, status, expected)
        assert bytes(source) == old_source and bytes(page) == old_page, n
        result = bytes(output)
        assert result[:32] == b"\xb8" * 32, n
        assert result[32 + reply_length:] == b"\xb8" * 32 + b"\0", n
        if reply_length < 16:
            assert result[32:32 + reply_length] == b"\xb8" * reply_length, n
        else:
            assert struct.unpack_from("<2Q", result, 32) == (expected, value), n
            assert result[48:32 + reply_length] == b"\xb8" * (reply_length - 16), n
        counts[str(expected)] = counts.get(str(expected), 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    opts = parser.parse_args()
    if opts.expect_unsafe:
        f = ctypes.CDLL(str(opts.library.resolve())).f0
        f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        f.restype = ctypes.c_uint32
        req = make_request()
        root = make_root({0: 0x2083})
        request = ctypes.create_string_buffer(req)
        table = ctypes.create_string_buffer(root)
        response = ctypes.create_string_buffer(16)
        assert oracle(req, root, 16) == (7, 0)
        assert f(request, len(req), response, 16, table, SIZE) == 0
        print("Unconditional native HIA root admission: REJECTED by oracle")
        return
    assert object_text(opts.library) == object_text("build/x86-cr3-root.o")
    corpus = cases()
    counts = run(opts.library, corpus)
    readonly_root_page(opts.library)
    assert counts.get("0", 0) > 10 and counts.get("5", 0) > 10
    assert counts.get("6", 0) > 10 and counts.get("7", 0) > 10
    report = {
        "schema": "heptakernel.hia-cr3-root-native.v1",
        "status": "PASS",
        "cases": len(corpus),
        "status_counts": counts,
        "source_sha256": hashlib.sha256(Path("src/x86_cr3_root.hepta").read_bytes()).hexdigest(),
        "object_sha256": hashlib.sha256(Path("build/x86-cr3-root.o").read_bytes()).hexdigest(),
        "native_hia": True,
        "readonly_os_page_cases": 1,
        "snapshot_authenticated": False,
        "hardware_cr3_access": False,
        "linux_full_acceptance": "HOLD",
    }
    Path("build/x86-cr3-root-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
