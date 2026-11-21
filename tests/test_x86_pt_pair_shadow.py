#!/usr/bin/env python3
"""Independent byte-oracle and dishonest-HIA control for off-line PTE shadow construction."""
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
    return (bool(value & 1) and not (value & RESERVED) and bool(phys)
            and not (phys >> width)
            and not ((value & 2) and not (value & NX))
            and not ((value & NX) and not (caps & 256))
            and not ((value & 256) and not (caps & 512)))


def oracle(payload, output_size, receipt_size):
    if receipt_size != 16:
        return 1, None, None
    if len(payload) != 4160:
        return 2, None, None
    if output_size != 4096:
        return 3, None, None
    a, old_a, new_a, b, old_b, new_b, caps, reserved = struct.unpack_from("<8Q", payload)
    snapshot = payload[64:]
    if a >= 512 or b >= 512 or a == b:
        return 4, None, None
    width = caps & 255
    if caps > 1023 or not (32 <= width <= 52) or reserved:
        return 5, None, None
    if not leaf_ok(new_a, caps, width) or not leaf_ok(new_b, caps, width):
        return 6, None, None
    if (new_a & PHYS) == (new_b & PHYS):
        return 6, None, None
    if struct.unpack_from("<Q", snapshot, a * 8)[0] != old_a:
        return 7, None, None
    if struct.unpack_from("<Q", snapshot, b * 8)[0] != old_b:
        return 7, None, None
    shadow = bytearray(snapshot)
    struct.pack_into("<Q", shadow, a * 8, new_a)
    struct.pack_into("<Q", shadow, b * 8, new_b)
    return 0, bytes(shadow), struct.pack("<QQ", new_a, new_b)


def native_entry(path):
    f = ctypes.CDLL(str(path.resolve())).f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_size_t] * 3
    f.restype = ctypes.c_uint32
    return f


def text_identity(obj, so):
    with tempfile.TemporaryDirectory() as tmp:
        blobs = []
        for idx, path in enumerate((obj, so)):
            dst = Path(tmp) / str(idx)
            subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                            str(path.resolve()), str(dst)], check=True)
            blobs.append(dst.read_bytes())
        assert blobs[0] and blobs[0] == blobs[1], "native HIA object/shared .text mismatch"
        return hashlib.sha256(blobs[0]).hexdigest()


def run(library, unsafe):
    native = native_entry(library)
    rng = random.Random(0x2026112102)
    counts = {i: 0 for i in range(8)}
    differences = cases = accepted = 0
    controls = {"stale_second_shadow_unchanged": False,
                "reverse_slot_order": False, "snapshot_preserved": False,
                "other_510_entries_identical": False}

    def case(payload, output_size=4096, receipt_size=16, stale_second=False, reverse=False):
        nonlocal differences, cases, accepted
        code, wanted_shadow, wanted_receipt = oracle(payload, output_size, receipt_size)
        src = ctypes.create_string_buffer(b"\\x93" * GUARD + payload + b"\\x93" * GUARD)
        dst = ctypes.create_string_buffer(b"\\x72" * GUARD + b"\\x72" * output_size + b"\\x72" * GUARD)
        rec = ctypes.create_string_buffer(b"\\xe9" * GUARD + b"\\xe9" * receipt_size + b"\\xe9" * GUARD)
        source_before = bytes(src)
        observed = native(ctypes.addressof(src) + GUARD, len(payload),
                          ctypes.addressof(dst) + GUARD, output_size,
                          ctypes.addressof(rec) + GUARD, receipt_size)
        new_shadow = bytes(dst)[GUARD:GUARD + output_size]
        new_receipt = bytes(rec)[GUARD:GUARD + receipt_size]
        expected_shadow = wanted_shadow if wanted_shadow is not None else b"\\x72" * output_size
        expected_receipt = wanted_receipt if wanted_receipt is not None else b"\\xe9" * receipt_size
        mismatch = (observed != code or new_shadow != expected_shadow or new_receipt != expected_receipt)
        cases += 1
        counts[code] += 1
        accepted += code == 0
        differences += mismatch
        assert bytes(src) == source_before, ("input modified", cases)
        assert bytes(dst)[:GUARD] == b"\\x72" * GUARD
        assert bytes(dst)[GUARD + output_size:GUARD + output_size + GUARD] == b"\\x72" * GUARD
        assert bytes(rec)[:GUARD] == b"\\xe9" * GUARD
        assert bytes(rec)[GUARD + receipt_size:GUARD + receipt_size + GUARD] == b"\\xe9" * GUARD
        if not unsafe:
            assert not mismatch, (cases, code, observed, new_shadow[:32].hex())
            if code == 0:
                controls["snapshot_preserved"] = bytes(src) == source_before
                a, _, _, b, _, _, _, _ = struct.unpack_from("<8Q", payload)
                snapshot = payload[64:]
                controls["other_510_entries_identical"] = all(
                    new_shadow[i * 8:i * 8 + 8] == snapshot[i * 8:i * 8 + 8]
                    for i in range(512) if i not in (a, b))
            if stale_second:
                assert code == 7 and new_shadow == b"\\x72" * output_size
                controls["stale_second_shadow_unchanged"] = True
            if reverse:
                assert code == 0
                controls["reverse_slot_order"] = True

    def valid(a=7, b=11, writable=False):
        page = bytearray(rng.randbytes(4096))
        old_a = rng.getrandbits(64)
        old_b = rng.getrandbits(64)
        struct.pack_into("<Q", page, a * 8, old_a)
        struct.pack_into("<Q", page, b * 8, old_b)
        frame_a = rng.randrange(0x100, 0x2000) << 12
        frame_b = frame_a + 4096
        new_a = frame_a | 5
        new_b = frame_b | 5
        if writable:
            new_a = frame_a | 7 | NX
            new_b = frame_b | 7 | NX
        header = struct.pack("<8Q", a, old_a, new_a, b, old_b, new_b, CAP, 0)
        return header, bytes(page)

    for _ in range(170):
        a, b = rng.sample(range(512), 2)
        header, snapshot = valid(a, b, writable=bool(rng.getrandbits(1)))
        case(header + snapshot, reverse=a > b)
        vals = list(struct.unpack("<8Q", header))
        vals[4] ^= 1
        case(struct.pack("<8Q", *vals) + snapshot, stale_second=True)
        vals = list(struct.unpack("<8Q", header))
        vals[1] ^= 1
        case(struct.pack("<8Q", *vals) + snapshot)
        vals = list(struct.unpack("<8Q", header))
        vals[3] = vals[0]
        case(struct.pack("<8Q", *vals) + snapshot)
        vals = list(struct.unpack("<8Q", header))
        vals[3] = 512
        case(struct.pack("<8Q", *vals) + snapshot)
        vals = list(struct.unpack("<8Q", header))
        vals[6] = 31
        case(struct.pack("<8Q", *vals) + snapshot)
        vals = list(struct.unpack("<8Q", header))
        vals[7] = 1
        case(struct.pack("<8Q", *vals) + snapshot)
        vals = list(struct.unpack("<8Q", header))
        vals[2] |= RESERVED
        case(struct.pack("<8Q", *vals) + snapshot)
        vals = list(struct.unpack("<8Q", header))
        vals[2] = vals[5]
        case(struct.pack("<8Q", *vals) + snapshot)
        vals = list(struct.unpack("<8Q", header))
        vals[2] = (vals[2] & ~NX) | 2
        case(struct.pack("<8Q", *vals) + snapshot)
    header, snapshot = valid()
    for payload in (b"", header[:63] + snapshot, header + snapshot + b"x"):
        case(payload)
    for output_size in (0, 1, 4095, 4097):
        case(header + snapshot, output_size=output_size)
    for receipt_size in (0, 1, 15, 17, 24):
        case(header + snapshot, receipt_size=receipt_size)
    assert cases >= 1700 and accepted >= 170
    assert all(counts[k] > 0 for k in counts), counts
    if unsafe:
        assert differences >= 1000, differences
    else:
        assert differences == 0 and all(controls.values()), controls
    return {
        "schema": "heptakernel.hia-two-pte-offline-shadow.v1",
        "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
        "native_hia": True, "cases": cases, "accepted": accepted,
        "oracle_divergences": differences, "counts": counts, "controls": controls,
        "source_snapshot_and_output_separate": True,
        "live_pte_modified": False, "atomic_parent_publish": False,
        "source_exclusive_ownership_proven": False, "concurrent_mutation_safe": False,
        "smp_proven": False, "full_linux_acceptance": "HOLD",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--object", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    result = run(args.library, args.expect_unsafe)
    if args.object:
        result["text_sha256"] = text_identity(args.object, args.library)
    print(json.dumps(result, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/x86-pt-pair-shadow-report.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
