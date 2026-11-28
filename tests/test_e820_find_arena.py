# SPDX-License-Identifier: GPL-2.0-only
"""Build and exercise the real E820 discovery HIA f0 entry."""
import ctypes
import hashlib
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile

PIN = "87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54"
ROOT = Path(__file__).resolve().parents[1]
PAGE = 4096
TOP = 1 << 52
MAX = (1 << 64) - 1
P = ctypes.c_void_p
N = ctypes.c_size_t


def wire(start, stop, pages, align, rows):
    return struct.pack("<5Q", start, stop, pages, align, len(rows)) + b"".join(
        struct.pack("<QQII", *r) for r in rows
    )


def oracle(w):
    if len(w) < 40:
        return 6, 0
    lo, hi, pages, align, count = struct.unpack_from("<5Q", w)
    if not (count <= 128 and len(w) == 40 + 24 * count and
            PAGE <= lo < hi <= TOP and lo % PAGE == hi % PAGE == 0 and
            1 <= pages <= 65536 and PAGE <= align <= TOP and align & (align - 1) == 0):
        return 6, 0
    usable, blocked = [], []
    for base, length, kind, attrs in struct.iter_unpack("<QQII", w[40:]):
        if length == 0 or base + length > MAX:
            return 6, 0
        if attrs & 1:
            (usable if kind == 1 and not (attrs & 2) else blocked).append((base, base + length))
    merged = []
    for a, b in sorted(usable):
        if merged and a <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(merged[-1][1], b)
        else:
            merged.append((a, b))
    # Enumerate every aligned address in the oracle's bounded fixtures. This
    # deliberately does not use the subject's endpoint sweep.
    span = pages * PAGE
    for start in range((lo + align - 1) // align * align, hi - span + 1, align):
        end = start + span
        if (any(a <= start and end <= b for a, b in merged) and
                not any(a < end and start < b for a, b in blocked)):
            return 0, start
    return 5, 0


def check(f0, w, size=16, expected=None):
    before = b"\xa5" * 16
    guard = b"\x5a" * 8
    src = ctypes.create_string_buffer(guard + w + guard)
    dest = ctypes.create_string_buffer(guard + before + guard)
    unused = ctypes.create_string_buffer(guard + guard)
    status = f0(ctypes.addressof(src) + 8, len(w), ctypes.addressof(dest) + 8, size,
                ctypes.addressof(unused), 16)
    if expected is None:
        expected = (1, 0) if size < 16 else oracle(w)
    assert status == expected[0], (status, expected, w.hex())
    assert bytes(src) == guard + w + guard + b"\0"
    assert bytes(unused) == guard + guard + b"\0"
    reply = before if size < 16 else struct.pack("<QQ", *expected)
    assert bytes(dest) == guard + reply + guard + b"\0"


def suite(f0):
    lo, hi = PAGE, PAGE * 17
    ram = (lo, hi - lo, 1, 1)
    fixed = [
        wire(lo, hi, 1, PAGE, [ram]), wire(lo, hi, 1, PAGE, []),
        wire(lo, hi, 17, PAGE, [ram]), wire(lo, hi, 16, PAGE, [ram]),
        wire(lo, hi, 2, 4 * PAGE, [ram, (lo + 3 * PAGE, 1, 2, 1)]),
        wire(lo, hi, 2, 4 * PAGE, [ram, (lo + 3 * PAGE - 1, 1, 1, 3)]),
        wire(lo, hi, 1, PAGE, [ram, (lo, 1, 1, 3)]),
        wire(lo, hi, 1, PAGE, [ram, (lo, 1, 1, 2)]),
        wire(lo, hi, 1, PAGE, [ram, (lo, 1, 0, 1)]),
        wire(lo, hi, 1, PAGE, [(lo + 33, PAGE - 33, 1, 5), (lo, 33, 1, 1)]),
        wire(lo, hi, 1, PAGE, [(lo + 34, PAGE - 34, 1, 5), (lo, 33, 1, 1)]),
        wire(lo, hi, 1, PAGE, [ram, (MAX, 1, 1, 0)]),
        wire(lo, hi, 1, PAGE, [ram, (MAX - 1, 1, 1, 0)]),
        wire(lo, hi, 1, PAGE, [ram, (lo, 0, 1, 0)]),
        wire(lo, hi, 1, PAGE, [ram] * 128),
        wire(lo, hi, 1, PAGE, [ram] * 129),
        wire(TOP - 8 * PAGE, TOP, 2, 2 * PAGE, [(TOP - 4 * PAGE, 4 * PAGE, 1, 1)]),
        wire(TOP - PAGE, TOP, 1, PAGE, [(TOP - PAGE, PAGE, 1, 1)]),
        wire(TOP - PAGE, TOP, 1, TOP, [(0, TOP, 1, 1)]),
        wire(lo, hi, 0, PAGE, [ram]), wire(lo, hi, 65537, PAGE, [ram]),
        wire(0, hi, 1, PAGE, [ram]), wire(lo + 1, hi, 1, PAGE, [ram]),
        wire(lo, lo, 1, PAGE, [ram]), wire(lo, hi + 1, 1, PAGE, [ram]),
        wire(lo, hi, 1, 0, [ram]), wire(lo, hi, 1, 2, [ram]),
        wire(lo, hi, 1, 3 * PAGE, [ram]), wire(lo, hi, 1, 2 * TOP, [ram]),
        wire(lo, hi, 1, PAGE, [ram]) + b"\0", wire(lo, hi, 1, PAGE, [ram])[:-1],
        b"", bytes(39), struct.pack("<5Q", lo, hi, 1, PAGE, MAX),
    ]
    # Maximum split-event shape with only the last page eligible.
    fixed.append(wire(lo, lo + 129 * PAGE, 1, PAGE, [
        (lo + i * PAGE + 1, 1, 1, 1) for i in range(127)
    ] + [(lo + 127 * PAGE, 2 * PAGE, 1, 1)]))
    for w in fixed:
        check(f0, w)
    # A machine-sized gap has an exact analytical result without enumerating
    # trillions of potential page addresses in the reference oracle.
    check(f0, wire(lo, TOP, 1, PAGE, [(TOP - PAGE, PAGE, 1, 1)]),
          expected=(0, TOP - PAGE))
    for n in range(16):
        check(f0, fixed[0], n)
    rng = random.Random(20261128)
    random_cases = 3000
    for _ in range(random_cases):
        lo = (rng.randrange(1, 9) * PAGE) + rng.choice([0, TOP - 32 * PAGE])
        hi = lo + rng.randrange(1, 17) * PAGE
        rows = []
        if rng.randrange(2):
            rows.append((lo, hi - lo, 1, 1))
        for _ in range(rng.randrange(24)):
            base = max(0, lo + rng.randrange(-PAGE, hi - lo + PAGE))
            size = rng.randint(1, 8 * PAGE)
            kind = rng.choice([1, 1, 1, 2, 3, 255])
            attrs = rng.choice([0, 1, 1, 1, 2, 3, 5, 0x80000001])
            rows.append((base, size, kind, attrs))
        rng.shuffle(rows)
        pages, align = rng.randrange(1, 7), PAGE << rng.randrange(5)
        check(f0, wire(lo, hi, pages, align, rows))
        check(f0, wire(lo, hi, pages, align, list(reversed(rows))))
    print(f"native HIA PASS: {len(fixed) + 1} fixed, 16 short replies, {2*random_cases} seeded calls")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_e820_find_arena.py /path/to/pinned-native-compiler")
    compiler = Path(sys.argv[1]).resolve(strict=True)
    if hashlib.sha256(compiler.read_bytes()).hexdigest() != PIN:
        raise SystemExit("wrong compiler SHA-256")
    src = (ROOT / "src/e820_find_arena.hepta").read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        obj = Path(tmp) / "subject.o"
        lib = Path(tmp) / "subject.so"
        first = subprocess.run([compiler], input=src, capture_output=True, check=True,
                               env={"PATH": ""}, timeout=30).stdout
        again = subprocess.run([compiler], input=src, capture_output=True, check=True,
                               env={"PATH": ""}, timeout=30).stdout
        assert first and first == again
        obj.write_bytes(first)
        assert subprocess.check_output(["nm", "-u", obj], timeout=30) == b""
        subprocess.run(["ld", "-shared", "-z", "noexecstack", "-o", lib, obj],
                       check=True, timeout=30)
        native = ctypes.CDLL(str(lib))
        f0 = native.f0
        f0.argtypes = [P, N, P, N, P, N]
        f0.restype = ctypes.c_uint32
        suite(f0)
        for name, data in [("source", src), ("object", first)]:
            print(name, hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
