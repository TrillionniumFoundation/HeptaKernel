#!/usr/bin/env python3
"""Independent byte-range oracle for the genuine HIA reservation-exclusion gate."""
from __future__ import annotations

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


def oracle(raw: bytes, reply_length: int = 16) -> tuple[int, int | None]:
    if reply_length < 16:
        return 1, None
    if len(raw) < 32:
        return 2, 0
    base, pages, prefix, count = struct.unpack_from("<4Q", raw)
    if count > 128 or len(raw) != 32 + 16 * count:
        return 2, 0
    if not (1 <= pages <= 65536 and prefix <= pages and base % PAGE == 0
            and base < LIMIT and pages * PAGE <= LIMIT - base):
        return 6, 0
    # The independent reference uses Python integer intervals, not bitsets
    # or the native HIA loop's early/late-return control flow.
    suffix = (base + prefix * PAGE, base + pages * PAGE)
    blocked = False
    for i in range(count):
        x, length = struct.unpack_from("<2Q", raw, 32 + i * 16)
        if length == 0 or length > MAX - x:
            return 6, 0
        blocked |= x < suffix[1] and x + length > suffix[0]
    return (5, 0) if blocked else (0, pages - prefix)


def encode(base, pages, prefix, rows, count=None):
    return struct.pack("<4Q", base, pages, prefix,
                       len(rows) if count is None else count) + b"".join(
        struct.pack("<2Q", *row) for row in rows)


def campaign(path: Path) -> dict:
    fn = ctypes.CDLL(str(path.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    checks = 0

    def check(raw, reply_length=16):
        nonlocal checks
        read = ctypes.create_string_buffer(b"\xa5" * 32 + raw + b"\xa5" * 32)
        reply = ctypes.create_string_buffer(b"\xb6" * (reply_length + 64))
        unused = ctypes.create_string_buffer(b"\xc7" * 64)
        before = bytes(read), bytes(unused)
        returned = fn(ctypes.addressof(read) + 32, len(raw),
                      ctypes.addressof(reply) + 32, reply_length,
                      ctypes.addressof(unused), 64)
        assert (bytes(read), bytes(unused)) == before, "HIA wrote an input/unused capability"
        data = bytes(reply)
        assert data[:32] == b"\xb6" * 32 and data[32 + reply_length:] == b"\xb6" * 32
        want = oracle(raw, reply_length)
        if reply_length < 16:
            assert data == b"\xb6" * (reply_length + 64), "short reply was modified"
            got = returned, None
        else:
            status, value = struct.unpack_from("<2Q", data, 32)
            assert data[48:32 + reply_length] == b"\xb6" * (reply_length - 16)
            assert returned == status
            got = status, value
        assert got == want, {"expected": want, "got": got, "input_hex": raw.hex()}
        checks += 1

    fixed = [
        (0x400000, 16, 0, []),
        (0x400000, 16, 3, [(0x400000, PAGE * 3)]),
        (0x400000, 16, 3, [(0x400000 + 2 * PAGE, PAGE * 2)]),
        (0x400000, 16, 3, [(0x400000 + 3 * PAGE, 1)]),
        (0x400000, 16, 3, [(0x400000 + 16 * PAGE, PAGE)]),
        (0x400000, 16, 3, [(0x400000 - PAGE, PAGE)]),
        (0x400000, 16, 16, [(0x400000, PAGE * 16)]),
        (0x400000, 16, 16, [(0x400000 + PAGE * 15, PAGE * 2)]),
        (0, 1, 0, [(0, 1)]),
        (LIMIT - PAGE, 1, 0, [(LIMIT - PAGE, PAGE)]),
        (LIMIT - PAGE, 1, 1, [(LIMIT - PAGE, PAGE)]),
        (0x400000, 16, 3, [(0x400000, 0)]),
        (0x400000, 16, 3, [(MAX, 2)]),
        (0x400000, 16, 3, [(0x400000 + 4 * PAGE, PAGE), (0, 0)]),
        (0x400001, 16, 0, []),
        (LIMIT, 1, 0, []),
        (LIMIT - PAGE, 2, 0, []),
        (0x400000, 0, 0, []),
        (0x400000, 65537, 0, []),
        (0x400000, 1, 2, []),
    ]
    for case in fixed:
        check(encode(*case))
    for raw in (b"", b"\0" * 31, encode(0x400000, 1, 0, []) + b"\0",
                encode(0x400000, 1, 0, [], count=1),
                encode(0x400000, 1, 0, [(0, 1)], count=129),
                encode(0x400000, 1, 0, [(0, 1)])[:-1]):
        check(raw)
    for n in (0, 1, 4, 16, 128):
        rows = [(0x200000 + i * PAGE, PAGE) for i in range(n)]
        check(encode(0x400000, 16, 0, rows))
        check(encode(0x400000, 16, 0, rows), reply_length=15)
        check(encode(0x400000, 16, 0, rows), reply_length=0)
        if n:
            rows[-1] = (0x400000 + 12 * PAGE, 1)
            check(encode(0x400000, 16, 0, rows))
    rng = random.Random(0x7E5E)
    for _ in range(1600):
        pages = rng.randint(1, 100)
        base = rng.choice([0, 0x400000, 0x800000, LIMIT - 101 * PAGE])
        prefix = rng.randint(0, pages)
        row_count = rng.randint(0, 32)
        rows = []
        for i in range(row_count):
            start = base + rng.randint(-4, pages + 4) * PAGE + rng.randint(0, PAGE - 1)
            start = max(0, start)
            length = rng.choice([0, 1, PAGE, PAGE * rng.randint(1, 3), MAX])
            rows.append((start, length))
        rng.shuffle(rows)
        check(encode(base, pages, prefix, rows))
    return {"status": "PASS", "cases": checks}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("library", type=Path)
    p.add_argument("--expect-unsafe", action="store_true")
    args = p.parse_args()
    if args.expect_unsafe:
        try:
            # A malicious native-HIA allow-all module must false-accept a real conflict.
            campaign(args.library)
        except AssertionError as exc:
            print("dishonest HIA reservation control rejected:", str(exc)[:400])
            return
        raise SystemExit("dishonest native HIA program escaped the oracle")
    result = campaign(args.library)
    Path("build/reservation-gate-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"native HIA physical reservation gate: {result['cases']} independent cases PASS")


if __name__ == "__main__":
    main()
