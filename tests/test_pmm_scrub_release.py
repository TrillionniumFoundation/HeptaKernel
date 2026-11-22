#!/usr/bin/env python3
"""Independent native oracle for an HIA 4KiB scrub-before-release transition.

A whole 130-byte two-zone PMM state and one caller-bound frame are tested.
The direct physical frame pointer, mapping exclusivity and CPU/DMA quiescence
are external preconditions, not established by this native routine.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct

from test_arena_router import object_text
from test_pmm_dual_claim import model as release_oracle, pair

PAGE = 4096
GUARD = 32
STATUS = {"request": 1, "state_shape": 2, "page_shape": 3,
          "invalid_state": 4, "not_owned": 6}


def reference(request, state, page, cap):
    # This independent model intentionally does not parse/execute HIA source.
    if len(request) != 8:
        return 1, state, page
    if len(state) != 130:
        return 2, state, page
    if cap != PAGE:
        return 3, state, page
    status, _, after = release_oracle(request, 16, state)
    return status, after, bytes(PAGE) if status == 0 else page


def compare(entry, case, ordinal):
    request, state, page, cap = case
    expected, after, new_page = reference(request, state, page, cap)
    if cap != len(page):
        assert cap == len(page), "test bug: inconsistent physical page length"
    source = ctypes.create_string_buffer(b"\xa1" * GUARD + request + b"\xa1" * GUARD)
    metadata = ctypes.create_string_buffer(b"\xb2" * GUARD + state + b"\xb2" * GUARD)
    frame = ctypes.create_string_buffer(b"\xc3" * GUARD + page + b"\xc3" * GUARD)
    old_source = bytes(source)
    status = entry(ctypes.addressof(source) + GUARD, len(request),
                   ctypes.addressof(metadata) + GUARD, len(state),
                   ctypes.addressof(frame) + GUARD, cap)
    actual_state = bytes(metadata)
    actual_page = bytes(frame)
    safe = (status == expected and bytes(source) == old_source
            and actual_state == b"\xb2" * GUARD + after + b"\xb2" * GUARD + b"\x00"
            and actual_page == b"\xc3" * GUARD + new_page + b"\xc3" * GUARD + b"\x00")
    if not safe:
        return (False, {"case": ordinal, "actual": status, "expected": expected,
                        "request": request.hex(), "state": state.hex(),
                        "page_sha256": hashlib.sha256(page).hexdigest(),
                        "state_observed_sha256": hashlib.sha256(actual_state).hexdigest()})
    return (True, None)


def cases():
    rng = random.Random(0x2026112214)
    first = pair(0b00000111, 0b00000111, reserved0=1, reserved1=1,
                 base0=0x500000, base1=0x700000)
    positive = [struct.pack("<Q", a) for a in (0x501000, 0x502000, 0x701000, 0x702000)]
    result = []
    for request in positive:
        for mode in range(32):
            page = bytes(rng.randrange(256) for _ in range(PAGE))
            result.append((request, first, page, PAGE))
    for req in (b"", b"\x00", b"\xff" * 7, b"\x01" * 9):
        result.append((req, first, bytes([0xD5]) * PAGE, PAGE))
    for n in (0, 1, 129, 131):
        result.append((positive[0], first[:n], bytes([0xB1]) * PAGE, PAGE))
    for n in (0, 1, 4095, 4097, 8192):
        result.append((positive[0], first, bytes([0xD3]) * n, n))
    for addr in (0, 0x500000, 0x503000, 0x700000, 0x703000,
                 0x501001, 0x502fff, 0xfffffffffffff000):
        result.append((struct.pack("<Q", addr), first, b"\xf5" * PAGE, PAGE))
    for _ in range(640):
        res_a, res_b = rng.randrange(9), rng.randrange(9)
        mask_a, mask_b = rng.randrange(256), rng.randrange(256)
        bases = rng.choice([(0x500000, 0x700000), (0x700000, 0x500000),
                            (0, 32768), ((1 << 52) - 32768, 0),
                            (0x500000, 0x501000)])
        state = pair(mask_a, mask_b, res_a, res_b, *bases)
        if rng.randrange(3) == 0:
            modified = bytearray(state)
            modified[rng.choice([0, 8, 16, 24, 32, 40, 64, 65, 73, 81, 89, 97, 105, 129])] ^= 1 << rng.randrange(8)
            state = bytes(modified)
        addr = rng.choice(bases) + rng.randrange(8) * PAGE
        if rng.randrange(5) == 0:
            addr += 1
        result.append((struct.pack("<Q",addr & 0xffffffffffffffff),
                       state, bytes(rng.randrange(256) for _ in range(PAGE)), PAGE))
    # Successful and rejected operations on the *same* page can be modeled
    # independently without inheriting state from the native implementation.
    state = first
    for _ in range(4):
        for request in positive:
            result.append((request, state, b"\xa5" * PAGE, PAGE))
            _, state, _ = reference(request, state, b"\xa5" * PAGE, PAGE)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--object", type=Path)
    ap.add_argument("--negative", action="store_true")
    ap.add_argument("--report", type=Path, default=Path("build/pmm-scrub-release-report.json"))
    args = ap.parse_args()
    dll = ctypes.CDLL(str(args.library.resolve()))
    entry = dll.f0
    entry.argtypes = (ctypes.c_void_p, ctypes.c_uint64) * 3
    entry.restype = ctypes.c_uint32
    if not args.negative:
        assert args.object is not None
        assert object_text(args.object) == object_text(args.library)
    observations = []
    tested = cases()
    mismatches = 0
    try:
        for i, case in enumerate(tested):
            ok, detail = compare(entry, case, i)
            if not ok:
                mismatches += 1
                if len(observations) < 8:
                    observations.append(detail)
        if args.negative:
            assert mismatches >= 100, ("dishonest HIA was not detected", mismatches)
        else:
            assert mismatches == 0, ("native HIA differs from independent oracle", observations)
    finally:
        report = {
            "schema": "heptakernel.hia-pmm-scrub-release-native.v1",
            "source_sha256": hashlib.sha256(Path("src/pmm_scrub_release.hepta").read_bytes()).hexdigest(),
            "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
            "object_sha256": (hashlib.sha256(args.object.read_bytes()).hexdigest() if args.object else None),
            "case_count": len(tested),
            "mismatches": mismatches,
            "examples": observations,
            "negative_control": args.negative,
            "status": ("DETECTED" if args.negative and mismatches >= 100
                       else "PASS" if not args.negative and mismatches == 0 else "FAIL"),
            "physical_frame_pointer_authenticated": False,
            "cpu_dma_quiescence": False,
            "atomic_smp": False,
            "full_linux": "HOLD",
        }
        if not args.negative:
            args.report.parent.mkdir(exist_ok=True, parents=True)
            args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "examples"}, sort_keys=True))
    if args.negative:
        assert mismatches >= 100
    else:
        assert mismatches == 0


if __name__ == "__main__":
    main()
