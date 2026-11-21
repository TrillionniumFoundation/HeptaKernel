#!/usr/bin/env python3
"""Independent byte oracle for native HIA two-PTE prevalidated single-owner commit."""
import argparse
import ctypes
import hashlib
import json
import random
import struct
import subprocess
import tempfile
from pathlib import Path

MASK = (1 << 64) - 1
PHYS = 0x000ffffffffff000
RESERVED = 0x7ff0000000000000
NX = 1 << 63
GUARD = 32
CAP = 48 | (1 << 8) | (1 << 9)


def leaf_ok(value, caps, width):
    phys = value & PHYS
    return (bool(value & 1) and not value & RESERVED and bool(phys)
            and not (phys >> width)
            and not ((value & 2) and not (value & NX))
            and not ((value & NX) and not (caps & 256))
            and not ((value & 256) and not (caps & 512)))


def oracle(request, table, receipt_size):
    if receipt_size != 16:
        return 1, table, None
    if len(request) != 64:
        return 2, table, None
    if len(table) != 4096:
        return 3, table, None
    a, old_a, new_a, b, old_b, new_b, caps, reserved = struct.unpack("<8Q", request)
    if a >= 512 or b >= 512 or a == b:
        return 4, table, None
    width = caps & 255
    if caps > 1023 or not (32 <= width <= 52) or reserved:
        return 5, table, None
    if not leaf_ok(new_a, caps, width) or not leaf_ok(new_b, caps, width):
        return 6, table, None
    if (new_a & PHYS) == (new_b & PHYS):
        return 6, table, None
    if struct.unpack_from("<Q", table, a * 8)[0] != old_a:
        return 7, table, None
    if struct.unpack_from("<Q", table, b * 8)[0] != old_b:
        return 7, table, None
    updated = bytearray(table)
    struct.pack_into("<Q", updated, a * 8, new_a)
    struct.pack_into("<Q", updated, b * 8, new_b)
    return 0, bytes(updated), struct.pack("<QQ", new_a, new_b)


def entrypoint(path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_size_t] * 3
    f.restype = ctypes.c_uint32
    return f


def text_identity(obj, so):
    with tempfile.TemporaryDirectory() as tmp:
        binaries = []
        for idx, path in enumerate((obj, so)):
            out = Path(tmp) / str(idx)
            subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                            str(path.resolve()), str(out)], check=True)
            binaries.append(out.read_bytes())
        assert binaries[0] and binaries[0] == binaries[1]
        return hashlib.sha256(binaries[0]).hexdigest()


def test(path, unsafe):
    native = entrypoint(path)
    rng = random.Random(0x20261121)
    counts = {i: 0 for i in range(8)}
    cases = diverged = accepted = 0
    special = {"stale_second_unchanged": False, "reverse_slot_order": False}

    def case(request, table, receipt_size=16, stale_second=False, reverse=False):
        nonlocal cases, diverged, accepted
        before_t = table
        expected, target_table, target_receipt = oracle(request, table, receipt_size)
        rb = ctypes.create_string_buffer(b"\x93" * GUARD + request + b"\x93" * GUARD)
        tb = ctypes.create_string_buffer(b"\x72" * GUARD + table + b"\x72" * GUARD)
        ob = ctypes.create_string_buffer(b"\xe9" * GUARD + b"\xe9" * receipt_size + b"\xe9" * GUARD)
        original_r = bytes(rb)
        result = native(ctypes.addressof(rb) + GUARD, len(request),
                        ctypes.addressof(tb) + GUARD, len(table),
                        ctypes.addressof(ob) + GUARD, receipt_size)
        observed_table = bytes(tb)[GUARD:GUARD + len(table)]
        observed_receipt = bytes(ob)[GUARD:GUARD + receipt_size]
        wanted_receipt = target_receipt if target_receipt is not None else b"\xe9" * receipt_size
        mismatch = result != expected or observed_table != target_table or observed_receipt != wanted_receipt
        cases += 1
        counts[expected] += 1
        accepted += expected == 0
        diverged += mismatch
        assert bytes(rb) == original_r, ("request modified", cases)
        assert bytes(tb)[:GUARD] == b"\x72" * GUARD
        assert bytes(tb)[GUARD + len(table):] == b"\x72" * GUARD
        assert bytes(ob)[:GUARD] == b"\xe9" * GUARD
        assert bytes(ob)[GUARD + receipt_size:] == b"\xe9" * GUARD
        if not unsafe:
            assert not mismatch, (cases, expected, result, observed_table[:32].hex())
            if stale_second:
                assert expected == 7 and observed_table == before_t
                special["stale_second_unchanged"] = True
            if reverse:
                assert expected == 0
                special["reverse_slot_order"] = True

    def valid_pair(a=7, b=11, writable=False):
        ta = bytearray(rng.randbytes(4096))
        oa = rng.getrandbits(64)
        ob = rng.getrandbits(64)
        struct.pack_into("<Q", ta, a * 8, oa)
        struct.pack_into("<Q", ta, b * 8, ob)
        base_a = rng.randrange(0x100, 0x2000) << 12
        base_b = base_a + 4096
        va = base_a | 5
        vb = base_b | 5
        if writable:
            va = base_a | 7 | NX
            vb = base_b | 7 | NX
        wire = struct.pack("<8Q", a, oa, va, b, ob, vb, CAP, 0)
        return wire, bytes(ta)

    for _ in range(170):
        a, b = rng.sample(range(512), 2)
        wire, table = valid_pair(a, b, writable=bool(rng.getrandbits(1)))
        case(wire, table, reverse=a > b)
        vals = list(struct.unpack("<8Q", wire))
        vals[4] ^= 1
        case(struct.pack("<8Q", *vals), table, stale_second=True)
        vals = list(struct.unpack("<8Q", wire))
        vals[1] ^= 1
        case(struct.pack("<8Q", *vals), table)
        vals = list(struct.unpack("<8Q", wire))
        vals[3] = vals[0]
        case(struct.pack("<8Q", *vals), table)
        vals = list(struct.unpack("<8Q", wire))
        vals[3] = 512
        case(struct.pack("<8Q", *vals), table)
        vals = list(struct.unpack("<8Q", wire))
        vals[6] = 31
        case(struct.pack("<8Q", *vals), table)
        vals = list(struct.unpack("<8Q", wire))
        vals[7] = 1
        case(struct.pack("<8Q", *vals), table)
        vals = list(struct.unpack("<8Q", wire))
        vals[2] |= RESERVED
        case(struct.pack("<8Q", *vals), table)
        vals = list(struct.unpack("<8Q", wire))
        vals[2] = vals[5]
        case(struct.pack("<8Q", *vals), table)
        vals = list(struct.unpack("<8Q", wire))
        vals[2] = (vals[2] & ~NX) | 2
        case(struct.pack("<8Q", *vals), table)
    wire, table = valid_pair()
    for request in (b"", wire[:63], wire + b"x"):
        case(request, table)
    for altered_table in (table[:4095], table + b"x"):
        case(wire, altered_table)
    for receipt_size in (0, 1, 15, 17, 24):
        case(wire, table, receipt_size=receipt_size)
    assert cases >= 1700 and accepted >= 170
    assert all(counts[x] > 0 for x in range(8)), counts
    if unsafe:
        assert diverged >= 1000, diverged
    else:
        assert diverged == 0 and all(special.values())
    return {
        "schema":"heptakernel.hia-two-pte-prevalidated.v1",
        "status":"NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
        "native_hia":True, "cases":cases, "accepted":accepted,
        "counts":counts, "oracle_divergences":diverged, "controls":special,
        "prewrite_both_old_checked":True,
        "single_owner_assumed":True, "atomic_pair_or_crash_safe":False,
        "hardware_tlb_invalidation":False, "smp_proven":False,
        "full_linux_acceptance":"HOLD",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    result = test(args.library, args.expect_unsafe)
    if args.object:
        result["text_sha256"] = text_identity(args.object, args.library)
    print(json.dumps(result, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/x86-pt-pair-report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
