#!/usr/bin/env python3
"""Independent byte oracle for a HIA one-call zero-before-claim transition.

Only an exclusive, externally authenticated page mapping is assumed.  No
hardware mapping provenance, atomics or SMP synchronization is inferred.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess

MAGIC = 3552580688320940353
LIMIT = 1 << 52
PAGE = 4096
ZONE = 65
GUARD = 32


def zone(base, reserved, used, *, free_override=None):
    bits = used | ((1 << reserved) - 1)
    free = 8 - bits.bit_count() if free_override is None else free_override
    return struct.pack("<5Q", MAGIC, 8, base, reserved, free) + bytes(24) + bytes([bits])


def pair(bits0=0, bits1=0, res0=1, res1=1, base0=0x500000, base1=0x700000):
    return zone(base0, res0, bits0) + zone(base1, res1, bits1)


def reference(request, state, page):
    if len(request) != 8:
        return 1, state, page
    if len(state) != 130:
        return 2, state, page
    if len(page) != PAGE:
        return 3, state, page
    blocks = []
    for off in (0, ZONE):
        m, count, base, reserved, free = struct.unpack_from("<5Q", state, off)
        bits = state[off + 64]
        ok = (m == MAGIC and count == 8 and reserved <= 8 and free <= 8
              and base % PAGE == 0 and base < LIMIT and LIMIT - base >= 8 * PAGE
              and state[off + 40:off + 64] == bytes(24)
              and bits & ((1 << reserved) - 1) == ((1 << reserved) - 1)
              and free == 8 - bits.bit_count())
        if not ok:
            return 4, state, page
        blocks.append((off, base, reserved, bits, free))
    b0, b1 = blocks[0][1], blocks[1][1]
    if b0 < b1 + 8 * PAGE and b1 < b0 + 8 * PAGE:
        return 4, state, page
    requested, = struct.unpack("<Q", request)
    if requested % PAGE:
        return 6, state, page
    for off, base, reserved, bitmap, free in blocks:
        if base <= requested < base + 8 * PAGE:
            idx = (requested - base) // PAGE
            if idx < reserved or bitmap & (1 << idx):
                return 6, state, page
            out = bytearray(state)
            out[off + 64] |= 1 << idx
            struct.pack_into("<Q", out, off + 32, free - 1)
            return 0, bytes(out), bytes(PAGE)
    return 6, state, page


def cases():
    rng = random.Random(0x202611221701)
    first = pair()
    tests = []
    for addr in (0x501000, 0x502000, 0x505000, 0x701000, 0x707000):
        for _ in range(25):
            tests.append((struct.pack("<Q", addr), first,
                          rng.randbytes(PAGE)))
    for req in (b"", b"\0", b"\0"*7, b"\0"*9):
        tests.append((req, first, b"\xa5"*PAGE))
    for n in (0, 1, 64, 129, 131):
        tests.append((struct.pack("<Q", 0x501000), first[:n], b"\xa5"*PAGE))
    for n in (0, 1, 4095, 4097, 8192):
        tests.append((struct.pack("<Q", 0x501000), first, b"\xa5"*n))
    for addr in (0, 0x500000, 0x503001, 0x700000, 0x701001,
                 0x508000, 0x6ff000, (1 << 52), (1 << 64) - PAGE):
        tests.append((struct.pack("<Q", addr), first, b"\xa5"*PAGE))
    for _ in range(920):
        res0, res1 = rng.randrange(9), rng.randrange(9)
        bits0, bits1 = rng.randrange(256), rng.randrange(256)
        ba, bb = rng.choice(((0x500000, 0x700000),
                             (0x700000, 0x500000), (0, 32768),
                             ((1 << 52) - 32768, 0), (0x500000, 0x501000)))
        state = pair(bits0, bits1, res0, res1, ba, bb)
        if rng.randrange(4) == 0:
            damaged = bytearray(state)
            at = rng.choice((0, 8, 16, 24, 32, 40, 64,
                             65, 73, 81, 89, 97, 105, 129))
            damaged[at] ^= (1 << rng.randrange(8))
            state = bytes(damaged)
        addr = rng.choice((ba, bb)) + PAGE * rng.randrange(8)
        if rng.randrange(8) == 0:
            addr += rng.choice((1, 4095))
        tests.append((struct.pack("<Q", addr & ((1 << 64)-1)), state,
                      rng.randbytes(PAGE)))
    # Independent consecutive calls: a second claim on the same frame is denied.
    state = pair()
    req = struct.pack("<Q", 0x501000)
    tests.append((req, state, b"\x94"*PAGE))
    status, state, _ = reference(req, state, b"\x94"*PAGE)
    assert status == 0
    tests.append((req, state, b"\xa6"*PAGE))
    return tests


def compare(fn, n, case):
    request, state, page = case
    want, next_state, next_page = reference(request, state, page)
    req = ctypes.create_string_buffer(b"\xa1"*GUARD + request + b"\xa1"*GUARD)
    st = ctypes.create_string_buffer(b"\xb2"*GUARD + state + b"\xb2"*GUARD)
    pg = ctypes.create_string_buffer(b"\xc3"*GUARD + page + b"\xc3"*GUARD)
    old_req = bytes(req)
    got = fn(ctypes.addressof(req)+GUARD, len(request),
             ctypes.addressof(st)+GUARD, len(state),
             ctypes.addressof(pg)+GUARD, len(page))
    good = (got == want and bytes(req) == old_req
            and bytes(st) == b"\xb2"*GUARD + next_state + b"\xb2"*GUARD + b"\0"
            and bytes(pg) == b"\xc3"*GUARD + next_page + b"\xc3"*GUARD + b"\0")
    return good, (n, got, want)


def text_section(path):
    return subprocess.check_output(["objcopy", "-O", "binary",
                                    "--only-section=.text", str(path), "/dev/stdout"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--object", type=Path)
    ap.add_argument("--negative", action="store_true")
    ap.add_argument("--source", type=Path, default=Path("src/pmm_scrub_claim.hepta"))
    ap.add_argument("--report", type=Path, default=Path("build/pmm-scrub-claim-report.json"))
    args = ap.parse_args()
    if not args.negative:
        assert args.object is not None
        assert text_section(args.object) == text_section(args.library)
    fn = ctypes.CDLL(str(args.library.resolve())).f0
    fn.argtypes = (ctypes.c_void_p, ctypes.c_uint64) * 3
    fn.restype = ctypes.c_uint32
    mismatches, bad = 0, []
    tested = cases()
    for i, case in enumerate(tested):
        okay, detail = compare(fn, i, case)
        if not okay:
            mismatches += 1
            if len(bad) < 6:
                bad.append(detail)
    passed = (mismatches >= 100 if args.negative else mismatches == 0)
    record = dict(schema="heptakernel.pmm-scrub-claim-native.v1",
                  source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  object_sha256=(hashlib.sha256(args.object.read_bytes()).hexdigest() if args.object else None),
                  library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest(),
                  cases=len(tested), mismatches=mismatches, first_mismatches=bad,
                  dishonest_control=args.negative,
                  status="DETECTED" if args.negative and passed else ("PASS" if passed else "FAIL"),
                  physical_pointer_authenticated=False, atomic_smp=False,
                  cpu_dma_quiescence=False, full_linux="HOLD")
    if not args.negative:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(record, indent=2, sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in record.items() if k != "first_mismatches"}, sort_keys=True))
    assert passed, bad


if __name__ == "__main__":
    main()
