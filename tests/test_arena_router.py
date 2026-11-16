#!/usr/bin/env python3
"""Independent set/interval oracle for native HIA multi-arena routing.

Scope: one read-only routing decision; E820 admission and physical allocation
are separate gates. This test never interprets HIA source or replaces its code.
"""
import argparse
import ctypes
import hashlib
import json
import random
import struct
from pathlib import Path

PAGE = 4096
LIMIT = 1 << 52
MAX = (1 << 64) - 1


def object_text(path):
    data = Path(path).read_bytes()
    assert data[:6] == b"\x7fELF\x02\x01"
    offset = struct.unpack_from("<Q", data, 40)[0]
    width, count, strings = struct.unpack_from("<3H", data, 58)
    heads = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * width) for i in range(count)]
    names = data[heads[strings][4]:heads[strings][4] + heads[strings][5]]
    for h in heads:
        if names[h[0]:].split(b"\0", 1)[0] == b".text":
            return data[h[4]:h[4] + h[5]]
    raise AssertionError("ELF lacks .text")


def encode(op, address, pages, arenas, count=None):
    return struct.pack("<4Q", op, address, pages,
                       len(arenas) if count is None else count) + b"".join(
        struct.pack("<3Q", *r) for r in arenas)


def oracle(data, rlen):
    if rlen < 16:
        return 1, None
    if len(data) < 32:
        return 2, 0
    op, address, pages, count = struct.unpack_from("<4Q", data)
    if count > 32 or len(data) != 32 + 24 * count:
        return 2, 0
    if op not in (0, 1, 2):
        return 3, 0
    if op == 0:
        if address or pages:
            return 6, 0
    elif op == 1:
        if not (address < LIMIT and address % PAGE == 0
                and 1 <= pages <= 65536 and pages * PAGE <= LIMIT - address):
            return 6, 0
    elif not (1 <= address <= 65536 and address & (address - 1) == 0
              and 1 <= pages <= 65536):
        return 6, 0
    arenas = [struct.unpack_from("<3Q", data, 32 + 24 * i) for i in range(count)]
    for base, n, reserved in arenas:
        if not (base < LIMIT and base % PAGE == 0 and 1 <= n <= 65536
                and reserved <= n and n * PAGE <= LIMIT - base):
            return 6, 0
    # Independent all-pairs reference, insensitive to descriptor order.
    for i, (x, n, _) in enumerate(arenas):
        for y, m, _ in arenas[i+1:]:
            if x < y + m * PAGE and y < x + n * PAGE:
                return 6, 0
    if op == 0:
        return 0, count
    if op == 2:
        # First-fit in wire order: an aligned geometric candidate, NOT a
        # free-frame allocation or a check of live ownership bitmaps.
        for base, n, reserved in arenas:
            first = base // PAGE + reserved
            aligned = (first + address - 1) & -address
            if aligned + pages <= base // PAGE + n:
                return 0, aligned * PAGE
        return 5, 0
    end = address + pages * PAGE
    for i, (base, n, reserved) in enumerate(arenas):
        if base + reserved * PAGE <= address and end <= base + n * PAGE:
            return 0, i + 1
    return 5, 0


def run(path, cases):
    entry = ctypes.CDLL(str(path.resolve())).f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint32
    for n, (request_bytes, rlen) in enumerate(cases):
        raw = ctypes.create_string_buffer(b"\xa7" * 32 + request_bytes + b"\xa7" * 32)
        reply = ctypes.create_string_buffer(b"\xb8" * (rlen + 64))
        state = ctypes.create_string_buffer(b"\xc9" * 64)
        original_raw, original_state = bytes(raw), bytes(state)
        observed = entry(ctypes.addressof(raw) + 32, len(request_bytes),
                         ctypes.addressof(reply) + 32, rlen, state, 64)
        expected, val = oracle(request_bytes, rlen)
        assert observed == expected, (n, observed, expected, request_bytes.hex())
        rb = bytes(reply)
        assert rb[:32] == b"\xb8" * 32 and rb[32 + rlen:] == b"\xb8" * 32 + b"\0"
        assert bytes(raw) == original_raw and bytes(state) == original_state
        if rlen < 16:
            assert rb[32:32+rlen] == b"\xb8" * rlen, n
        else:
            assert struct.unpack_from("<2Q", rb, 32) == (expected, val), n
            assert rb[48:32+rlen] == b"\xb8" * (rlen - 16), n
    return len(cases)


def cases():
    fixed = [
        (encode(0, 0, 0, []), 16),
        (encode(1, 0, 1, []), 16),
        (encode(0, 0, 0, [(0, 1, 0)]), 16),
        (encode(1, 0, 1, [(0, 1, 0)]), 16),
        (encode(1, 0, 1, [(0, 1, 1)]), 16),
        (encode(1, PAGE, 1, [(0, 2, 1)]), 16),
        (encode(1, 0, 1, [(0, 2, 1)]), 16),
        (encode(1, PAGE, 1, [(0, 2, 1), (2*PAGE, 2, 0)]), 16),
        (encode(1, 2*PAGE, 2, [(2*PAGE, 2, 0), (0, 2, 1)]), 16),
        (encode(1, 2*PAGE, 3, [(0, 2, 0), (2*PAGE, 3, 0)]), 16),
        (encode(1, LIMIT - PAGE, 1, [(LIMIT-PAGE, 1, 0)]), 16),
        (encode(0, 0, 0, [(0, 1, 0), (0, 1, 0)]), 16),
        (encode(0, 0, 0, [(0, 2, 0), (PAGE, 1, 0)]), 16),
        (encode(0, 0, 0, [(PAGE, 1, 0), (0, 2, 0)]), 16),
        (encode(0, 0, 0, [(0, 1, 2)]), 16),
        (encode(0, 0, 0, [(0, 0, 0)]), 16),
        (encode(0, 0, 0, [(1, 1, 0)]), 16),
        (encode(0, 0, 0, [(LIMIT, 1, 0)]), 16),
        (encode(0, 0, 0, [(LIMIT-PAGE, 2, 0)]), 16),
        (encode(0, 0, 0, [(MAX, MAX, MAX)]), 16),
        (encode(0, PAGE, 0, []), 16),
        (encode(0, 0, 1, []), 16),
        (encode(1, MAX, 1, []), 16),
        (encode(1, 0, 0, []), 16),
        (encode(1, LIMIT-PAGE, 2, []), 16),
        (encode(2, 4, 2, [(0x400000, 512, 3), (0x600000, 512, 1)]), 16),
        (encode(2, 8, 3, [(0x400000, 2, 2), (0x600000, 17, 1)]), 16),
        (encode(2, 2, 4, [(0x400000, 2, 1), (0x600000, 2, 1)]), 16),
        (encode(2, 1, 1, [(0, 1, 0)]), 16),
        (encode(2, 2, 1, [(0, 1, 0)]), 16),
        (encode(2, 65536, 1, [(LIMIT-PAGE, 1, 0)]), 16),
        (encode(2, 0, 1, [(0, 2, 0)]), 16),
        (encode(2, 3, 1, [(0, 2, 0)]), 16),
        (encode(2, 65537, 1, [(0, 2, 0)]), 16),
        (encode(2, 1, 0, [(0, 2, 0)]), 16),
        (encode(2, 1, 65537, [(0, 2, 0)]), 16),
        (encode(2, 0, 0, []), 16),
        (encode(MAX, 0, 0, []), 16),
        (encode(1, PAGE, 1, [(0, 2, 0)], count=2), 16),
        (encode(1, PAGE, 1, [(0, 2, 0)], count=MAX), 16),
        (encode(1, PAGE, 1, [(0, 2, 0)])[:-1], 16),
        (encode(1, PAGE, 1, [(0, 2, 0)])+b"\0", 16),
        (b"", 16), (b"\0" * 31, 16),
        (encode(1, 0, 1, [(0, 1, 0)]), 0),
        (encode(1, 0, 1, [(0, 1, 0)]), 15),
        (encode(1, 0, 1, [(0, 1, 0)]), 17),
        (encode(1, 0, 1, [(0, 1, 0)]), 32),
        (encode(0, 0, 0, [(i*2*PAGE, 1, 0) for i in range(32)]), 16),
        (encode(0, 0, 0, [(i*2*PAGE, 1, 0) for i in range(33)]), 16),
    ]
    rng = random.Random(0xA8E20261116)
    for _ in range(800):
        n = rng.randrange(0, 33)
        # Deliberately unsorted, disjoint, sometimes completely reserved arenas.
        selected = rng.sample(range(0, 4096), n)
        arenas = [(i*16*PAGE, rng.randrange(1, 17),
                   0) for i in selected]
        arenas = [(base, sz, rng.randrange(sz+1)) for base, sz, _ in arenas]
        rng.shuffle(arenas)
        if n and rng.randrange(2):
            chosen = rng.randrange(n)
            base, size, reserved = arenas[chosen]
            address = base + rng.randrange(size)*PAGE
            pages = rng.randrange(1, 18)
        else:
            address, pages = rng.randrange(0, 4096)*16*PAGE, rng.randrange(1, 18)
        op = rng.randrange(3)
        requested_address = address if op == 1 else (
            1 << rng.randrange(17) if op == 2 else 0)
        fixed.append((encode(op, requested_address,
                             pages if op else 0, arenas), rng.choice([16,16,16,16,24])))
    for _ in range(600):
        n = rng.randrange(0, 33)
        arenas = []
        for i in range(n):
            base = rng.choice([0, PAGE, 123, LIMIT-PAGE, LIMIT, MAX,
                               rng.randrange(256)*PAGE])
            size = rng.choice([0, 1, 2, 16, 65536, 65537, MAX])
            reserved = rng.choice([0, 1, size, MAX])
            arenas.append((base, size, reserved))
        op = rng.choice([0, 1, 2, 3, MAX])
        address = rng.choice([0, PAGE, 1, LIMIT-PAGE, LIMIT, MAX])
        pages = rng.choice([0, 1, 2, 65536, 65537, MAX])
        fixed.append((encode(op, address, pages, arenas), rng.choice([16,16,15,24])))
    return fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--expect-unsafe", action="store_true")
    ap.add_argument("--report", type=Path, default=Path("build/arena-router-report.json"))
    args = ap.parse_args()
    if args.expect_unsafe:
        # A separate, deliberately dishonest native HIA object must be detected.
        invalid = encode(1, 0, 1, [(0, 1, 1)])
        assert oracle(invalid, 16) == (5, 0)
        lib = ctypes.CDLL(str(args.library.resolve())).f0
        lib.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        lib.restype = ctypes.c_uint32
        buf = ctypes.create_string_buffer(invalid)
        response = ctypes.create_string_buffer(16)
        state = ctypes.create_string_buffer(16)
        status = lib(buf, len(invalid), response, 16, state, 16)
        assert status == 0 and status != oracle(invalid,16)[0]
        print(json.dumps({"status":"REJECTED", "negative_control":"dishonest native HIA",
                          "oracle_status":5, "observed_status":status}))
        return
    assert object_text(args.library) == object_text("build/arena-router.o")
    report = {"schema":"heptakernel.hia-arena-router-test.v1",
              "scope":"bounded read-only multi-arena validation, exact-range routing, and aligned first-fit candidate selection; not free-frame allocation",
              "qemu_tested":False,"linux_compatibility_tested":False,
              "source_sha256":hashlib.sha256(Path("src/arena_router.hepta").read_bytes()).hexdigest(),
              "object_sha256":hashlib.sha256(Path("build/arena-router.o").read_bytes()).hexdigest(),
              "library_sha256":hashlib.sha256(args.library.read_bytes()).hexdigest(),
              "object_text_matches_loaded_library":True}
    try:
        report["calls"] = run(args.library, cases())
        report["status"] = "PASS"
    except BaseException as exc:
        report.update(status="FAIL",error=repr(exc))
        raise
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,sort_keys=True))

if __name__ == "__main__":
    main()
