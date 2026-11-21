#!/usr/bin/env python3
"""Independent native HIA PMM-snapshot shadow-parent admission byte oracle."""
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
MAGIC = 3552580688320940353
LIMIT = 1 << 52
GUARD = 32


def oracle(req, state, receipt_size):
    if receipt_size != 16:
        return 1, None
    if len(req) != 64:
        return 2, None
    shadow, old, expected, proposed, base, pages, reserved, width = struct.unpack("<8Q", req)
    if not (1 <= pages <= 65536 and reserved < pages and base < LIMIT and base % PAGE == 0
            and pages * PAGE <= LIMIT - base and 32 <= width <= 52):
        return 4, None
    if len(state) != 64 + (pages + 7) // 8:
        return 3, None
    magic, count, actual_base, actual_reserved, free = struct.unpack_from("<5Q", state)
    if ((magic, count, actual_base, actual_reserved) != (MAGIC, pages, base, reserved)
            or free > pages - reserved):
        return 4, None
    if (not old or not shadow or old == shadow or old % PAGE or shadow % PAGE
            or old >= (1 << width) or shadow >= (1 << width)
            or expected != (old | 3) or proposed != (shadow | 3)):
        return 5, None
    if not (base <= old < base + pages * PAGE and base <= shadow < base + pages * PAGE):
        return 6, None
    i, j = (old - base) // PAGE, (shadow - base) // PAGE
    if i < reserved or j < reserved:
        return 6, None
    if not (state[64 + i // 8] & (1 << (i % 8))
            and state[64 + j // 8] & (1 << (j % 8))):
        return 7, None
    if state[40:64] != b"\0" * 24:
        return 4, None
    return 0, struct.pack("<QQ", proposed, shadow)


def state_for(base, pages, reserved, old_index, new_index):
    bits = bytearray((pages + 7) // 8)
    for index in list(range(reserved)) + [old_index, new_index]:
        bits[index // 8] |= 1 << (index % 8)
    header = struct.pack("<5Q", MAGIC, pages, base, reserved, pages - reserved - 2)
    return header + bytes(24) + bytes(bits)


def entry(lib):
    fn = ctypes.CDLL(str(lib.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t] * 3
    fn.restype = ctypes.c_uint32
    return fn


def text_identity(obj, so):
    with tempfile.TemporaryDirectory() as folder:
        pieces = []
        for i, p in enumerate((obj, so)):
            out = Path(folder) / str(i)
            subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                            str(p.resolve()), str(out)], check=True)
            pieces.append(out.read_bytes())
    assert pieces[0] and pieces[0] == pieces[1]
    return hashlib.sha256(pieces[0]).hexdigest()


def run(library, unsafe):
    fn = entry(library)
    rng = random.Random(202611210924)
    tested = accepted = disagreements = 0
    codes = {i: 0 for i in range(8)}

    def case(req, state, reply_size=16):
        nonlocal tested, accepted, disagreements
        wanted, reply = oracle(req, state, reply_size)
        src = ctypes.create_string_buffer(b"\x96" * GUARD + req + b"\x96" * GUARD)
        pmm = ctypes.create_string_buffer(b"\x51" * GUARD + state + b"\x51" * GUARD)
        result = ctypes.create_string_buffer(b"\xea" * GUARD + b"\xea" * reply_size + b"\xea" * GUARD)
        before_src, before_pmm = bytes(src), bytes(pmm)
        ret = fn(ctypes.addressof(src) + GUARD, len(req),
                 ctypes.addressof(result) + GUARD, reply_size,
                 ctypes.addressof(pmm) + GUARD, len(state))
        expected = reply if reply is not None else b"\xea" * reply_size
        actual = bytes(result)[GUARD:GUARD + reply_size]
        mismatch = ret != wanted or actual != expected
        disagreements += mismatch
        tested += 1
        accepted += wanted == 0
        codes[wanted] += 1
        assert bytes(src) == before_src and bytes(pmm) == before_pmm
        assert bytes(result)[:GUARD] == b"\xea" * GUARD
        assert bytes(result)[GUARD + reply_size:] == b"\xea" * GUARD
        if not unsafe:
            assert not mismatch, (tested, wanted, ret, expected.hex(), actual.hex())

    for k in range(96):
        pages = (8, 17, 32, 64, 128)[k % 5]
        reserved = rng.randrange(1, pages - 2)
        old_idx, new_idx = rng.sample(range(reserved, pages), 2)
        base = (0x200000 + k * 0x100000) & ~4095
        old, shadow = base + old_idx * PAGE, base + new_idx * PAGE
        req = struct.pack("<8Q", shadow, old, old | 3, shadow | 3,
                          base, pages, reserved, 48)
        pmm = state_for(base, pages, reserved, old_idx, new_idx)
        case(req, pmm)
        for slot, bad in ((0, shadow + 1), (1, 0), (2, old | 7), (3, shadow | 1),
                          (4, base + PAGE), (5, pages + 1), (6, pages),
                          (7, 31)):
            vals = list(struct.unpack("<8Q", req))
            vals[slot] = bad
            case(struct.pack("<8Q", *vals), pmm)
        case(req[:-1], pmm)
        case(req + b"x", pmm)
        case(req, pmm[:-1])
        case(req, pmm + b"x")
        case(req, pmm, 0)
        case(req, pmm, 15)
        case(req, pmm, 17)
        for field in (0, 8, 16, 24):
            corrupted = bytearray(pmm)
            corrupted[field] ^= 1
            case(req, bytes(corrupted))
        corrupt = bytearray(pmm)
        corrupt[32:40] = struct.pack("<Q", pages)
        case(req, bytes(corrupt))
        for index in (old_idx, new_idx):
            corrupt = bytearray(pmm)
            corrupt[64 + index // 8] &= ~(1 << (index % 8))
            case(req, bytes(corrupt))
        corrupt = bytearray(pmm)
        corrupt[40 + k % 24] = 1
        case(req, bytes(corrupt))
        vals = list(struct.unpack("<8Q", req))
        vals[0] = base + reserved * PAGE - PAGE
        vals[3] = vals[0] | 3
        case(struct.pack("<8Q", *vals), pmm)
    high = 0x1_0000_0000
    hi_old, hi_new = high + 3 * PAGE, high + 4 * PAGE
    high_state = state_for(high, 16, 1, 3, 4)
    high_request = struct.pack("<8Q", hi_new, hi_old, hi_old | 3,
                               hi_new | 3, high, 16, 1, 32)
    case(high_request, high_state)
    assert accepted == 96 and tested >= 2400 and all(codes.values()), (tested, accepted, codes)
    if unsafe:
        assert disagreements >= 2000, disagreements
    else:
        assert disagreements == 0
    return {"schema": "heptakernel.hia-shadow-frame-pmm-admission.v1",
            "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
            "cases": tested, "accepted": accepted, "counts": codes,
            "oracle_disagreements": disagreements,
            "pmm_snapshot_not_authenticated": True, "atomic_pte_publication": False,
            "smp_proven": False, "full_linux_acceptance": "HOLD"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("library", type=Path)
    p.add_argument("--object", type=Path)
    p.add_argument("--expect-unsafe", action="store_true")
    args = p.parse_args()
    result = run(args.library, args.expect_unsafe)
    if args.object:
        result["text_sha256"] = text_identity(args.object, args.library)
    print(json.dumps(result, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/x86-shadow-frame-admit-report.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
