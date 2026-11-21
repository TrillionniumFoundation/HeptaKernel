#!/usr/bin/env python3
"""Independent native HIA byte-copy oracle for an ELF staging buffer.

The caller must provide distinct nonoverlapping capabilities, an exclusive
destination owner and a stable source during the call. Neither authenticity
nor concurrent exclusion is established by this component.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import mmap
import random
import subprocess
import tempfile
from pathlib import Path

MINIMUM, MAXIMUM, RECEIPT, GUARD = 64, 1 << 20, 16, 32
MARKER = b"\xa5\x5a" + bytes(14)


def load(path: Path):
    function = ctypes.CDLL(str(path.resolve())).f0
    function.argtypes = [ctypes.c_void_p, ctypes.c_size_t] * 3
    function.restype = ctypes.c_uint32
    return function


def expected_status(size: int, stage_size: int, receipt_size: int) -> int:
    if not MINIMUM <= size <= MAXIMUM:
        return 1
    if size != stage_size:
        return 2
    if receipt_size != RECEIPT:
        return 3
    return 0


def guarded_copy(entry) -> str:
    if mmap.PAGESIZE != 4096:
        return "SKIPPED_PAGE_SIZE_MISMATCH"
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    memory = [mmap.mmap(-1, 3 * 4096, prot=mmap.PROT_READ | mmap.PROT_WRITE)
              for _ in range(2)]
    views = [(ctypes.c_ubyte * (3 * 4096)).from_buffer(m) for m in memory]
    addresses = [ctypes.addressof(v) for v in views]
    pattern = bytes(range(256)) * 16
    ctypes.memmove(addresses[0] + 4096, pattern, 4096)
    ctypes.memset(addresses[1] + 4096, 0x71, 4096)
    try:
        for address in addresses:
            assert libc.mprotect(address, 4096, 0) == 0
            assert libc.mprotect(address + 8192, 4096, 0) == 0
        assert libc.mprotect(addresses[0] + 4096, 4096, mmap.PROT_READ) == 0
        receipt = ctypes.create_string_buffer(RECEIPT)
        result = entry(addresses[0] + 4096, 4096,
                       addresses[1] + 4096, 4096,
                       ctypes.addressof(receipt), RECEIPT)
        assert result == 0 and receipt.raw == MARKER
        assert ctypes.string_at(addresses[0] + 4096, 4096) == pattern
        assert ctypes.string_at(addresses[1] + 4096, 4096) == pattern
        ctypes.memset(addresses[1] + 4096, 0x71, 4096)
        result = entry(addresses[0] + 4096, 4097,
                       addresses[1] + 4096, 4096,
                       ctypes.addressof(receipt), RECEIPT)
        assert result == 2
        assert ctypes.string_at(addresses[1] + 4096, 4096) == b"\x71" * 4096
    finally:
        for address in addresses:
            for offset in (0, 4096, 8192):
                assert libc.mprotect(address + offset, 4096,
                                    mmap.PROT_READ | mmap.PROT_WRITE) == 0
        views.clear()
        for m in memory:
            m.close()
    return "PASS"


def text_identity(obj: Path, lib: Path) -> str:
    with tempfile.TemporaryDirectory() as temporary:
        outputs = []
        for index, original in enumerate((obj, lib)):
            destination = Path(temporary) / f"{index}.text"
            subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                            str(original.resolve()), str(destination)], check=True)
            outputs.append(destination.read_bytes())
        assert outputs[0] and outputs[0] == outputs[1]
        return hashlib.sha256(outputs[0]).hexdigest()


def experiment(path: Path, unsafe: bool) -> dict:
    entry = load(path)
    rng = random.Random(0xEC202621)
    status_counts: dict[int, int] = {}
    count = divergences = accepted = 0

    def check(source: bytes, stage_size: int | None = None,
              receipt_size: int = RECEIPT, mutate_after: bool = False):
        nonlocal count, divergences, accepted
        if stage_size is None:
            stage_size = len(source)
        src = ctypes.create_string_buffer(b"\x63" * GUARD + source + b"\x63" * GUARD)
        dst = ctypes.create_string_buffer(b"\x71" * (stage_size + 2 * GUARD))
        rec = ctypes.create_string_buffer(b"\xe9" * (receipt_size + 2 * GUARD))
        original_source = bytes(src)
        status = expected_status(len(source), stage_size, receipt_size)
        observed = entry(ctypes.addressof(src) + GUARD, len(source),
                         ctypes.addressof(dst) + GUARD, stage_size,
                         ctypes.addressof(rec) + GUARD, receipt_size)
        stage = bytes(dst)[GUARD:GUARD + stage_size]
        receipt = bytes(rec)[GUARD:GUARD + receipt_size]
        wanted_stage = source if status == 0 else b"\x71" * stage_size
        wanted_receipt = MARKER if status == 0 else b"\xe9" * receipt_size
        mismatch = (observed != status or stage != wanted_stage
                    or receipt != wanted_receipt)
        count += 1
        accepted += status == 0
        divergences += mismatch
        status_counts[status] = status_counts.get(status, 0) + 1
        assert bytes(src) == original_source, ("source overwritten", count)
        assert bytes(dst)[:GUARD] == b"\x71" * GUARD
        assert bytes(dst)[GUARD + stage_size:GUARD + stage_size + GUARD] == b"\x71" * GUARD
        assert bytes(rec)[:GUARD] == b"\xe9" * GUARD
        assert bytes(rec)[GUARD + receipt_size:GUARD + receipt_size + GUARD] == b"\xe9" * GUARD
        if not unsafe:
            assert not mismatch, (count, status, observed, stage[:32], receipt)
            if mutate_after and status == 0 and source:
                ctypes.memset(ctypes.addressof(src) + GUARD, 0x11, len(source))
                assert bytes(dst)[GUARD:GUARD + stage_size] == source, (
                    "staging changed when caller modified source", count)

    for size in (0, 1, 63, 64, 65, 4095, 4096, 7292, 16384,
                 MAXIMUM, MAXIMUM + 1):
        source = bytes((i * 17 + 41) % 256 for i in range(size))
        check(source, mutate_after=True)
        for destination in (0, max(0, size - 1), size + 1):
            check(source, stage_size=destination)
    source = bytes((i * 3 + 19) % 256 for i in range(7292))
    for receipt_size in (0, 1, 15, 16, 17, 24):
        check(source, receipt_size=receipt_size)
    for _ in range(320):
        size = rng.choice((64, 65, 128, 4095, 4096, 7292, 9000, 16384))
        src = rng.randbytes(size)
        mode = rng.randrange(5)
        if mode == 0:
            check(src, mutate_after=True)
        elif mode == 1:
            check(src, stage_size=size - 1)
        elif mode == 2:
            check(src, stage_size=size + 1)
        elif mode == 3:
            check(src, receipt_size=15)
        else:
            check(src, receipt_size=17)
    assert accepted >= 50 and all(status_counts.get(s, 0) > 0 for s in range(4))
    if unsafe:
        assert divergences >= 200
    else:
        assert divergences == 0
    result = {"schema": "heptakernel.elf64-snapshot-stage.v1",
              "status": "NEGATIVE_CONTROL_REJECTED" if unsafe else "PASS",
              "cases": count, "accepted": accepted, "status_counts": status_counts,
              "oracle_divergences": divergences,
              "native_hia": True, "source_isolation_after_copy": True,
              "caller_ownership_and_nonaliasing_proven": False,
              "authenticated_snapshot": False, "smp_atomic": False,
              "full_linux_acceptance": "HOLD"}
    if not unsafe:
        result["readonly_source_guard_pages"] = guarded_copy(entry)
        assert result["readonly_source_guard_pages"] == "PASS"
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("library", type=Path)
    p.add_argument("--object", type=Path)
    p.add_argument("--expect-unsafe", action="store_true")
    args = p.parse_args()
    report = experiment(args.library, args.expect_unsafe)
    if args.object:
        report["text_sha256"] = text_identity(args.object, args.library)
    print(json.dumps(report, sort_keys=True))
    if not args.expect_unsafe:
        Path("build/elf64-stage-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
