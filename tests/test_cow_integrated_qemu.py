#!/usr/bin/env python3
"""QEMU hardware observer: exact native HIA page split then PTE swap.

This is a NON-HIA boot bridge; its results cannot close Linux COW,
SMP atomicity, privilege backend, or PMM authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
FAULT = "HEPTAKERNEL COW PTE REAL WRITE PROTECT FAULT OBSERVED"
PREP = "HEPTAKERNEL HIA COW INTEGRATED PAGE COPY AND COUNTS VERIFIED"
COMPLETE = "HEPTAKERNEL HIA COW INTEGRATED PF COPY REFCOUNT PTE VERIFIED"
STALE = "HEPTAKERNEL HIA COW INTEGRATED STALE REFCOUNT REFUSED"
REJECT = "HEPTAKERNEL HIA COW INTEGRATED DISHONEST OR CORRUPT COPY REJECTED"
PTE = "HEPTAKERNEL HIA COW PTE HARDWARE REMAP AND PHYSICAL RAM VERIFIED"
ABORT = "HEPTAKERNEL HIA COW INTEGRATED LATE PTE REJECT ABORT ZERO COUNTS RESTORED"
ABORT_BAD = "HEPTAKERNEL HIA COW INTEGRATED ABORT DISHONEST OR CORRUPT REJECTED"
GUARD_REFUSED = "HEPTAKERNEL HIA COW INTEGRATED LIVE PTE GUARDED ABORT REFUSED UNCHANGED"
RECYCLED = "HEPTAKERNEL HIA COW PMM FRAME FREED REISSUED ZERO VERIFIED"
DOUBLE_FREE = "HEPTAKERNEL HIA COW PMM DOUBLE FREE REFUSED STATE UNCHANGED"
FAIL = "HEPTAKERNEL BOOT FAIL"


def run(qemu: str, machine: str, mib: int, mode: str) -> dict:
    image = Path(f"build/cow-integrated-{mode}-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(mib), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    row = dict(machine=machine, memory_mib=mib, mode=mode,
               image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
               command=cmd)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", stdout=str(exc.stdout), stderr=str(exc.stderr))
        raise AssertionError(json.dumps(row, sort_keys=True)) from exc
    row.update(status="COMPLETED", returncode=p.returncode,
               stdout=p.stdout, stderr=p.stderr)
    out = p.stdout
    assert all(out.count(s) == 1 for s in (MAP, RESERV, FAULT)), row
    assert all(out.count(s) <= 1 for s in (PREP, COMPLETE, STALE, REJECT, PTE, ABORT, ABORT_BAD, GUARD_REFUSED, RECYCLED, DOUBLE_FREE)), row
    if mode == "hw":
        assert p.returncode == 75, row
        assert all(out.count(s) == 1 for s in (PREP, COMPLETE, PTE)), row
        assert STALE not in out and REJECT not in out and FAIL not in out, row
    elif mode in ("abort", "guarded", "recycle"):
        assert p.returncode == 35 and out.count(ABORT) == 1, row
        assert out.count(RECYCLED) == int(mode == "recycle") and DOUBLE_FREE not in out, row
        assert out.count(PREP) == 1 and FAIL in out, row
        assert all(x not in out for x in (COMPLETE, STALE, REJECT, PTE, ABORT_BAD)), row
    elif mode == "recycle-double":
        assert p.returncode == 35 and out.count(DOUBLE_FREE) == 1, row
        assert out.count(PREP) == 1 and FAIL in out, row
        assert all(x not in out for x in (COMPLETE, STALE, REJECT, PTE, ABORT, ABORT_BAD, GUARD_REFUSED, RECYCLED)), row
    elif mode in ("abort-noop", "guarded-noop"):
        assert p.returncode == 35 and out.count(ABORT_BAD) == 1, row
        assert out.count(PREP) == 1 and FAIL in out, row
        assert all(x not in out for x in (COMPLETE, STALE, REJECT, PTE, ABORT)), row
    elif mode in ("guarded-stale", "guarded-published"):
        assert p.returncode == 35 and out.count(GUARD_REFUSED) == 1, row
        assert out.count(PREP) == 1 and FAIL in out, row
        assert all(x not in out for x in (COMPLETE, STALE, REJECT, PTE, ABORT, ABORT_BAD)), row
    elif mode == "stale":
        assert p.returncode == 35 and out.count(STALE) == 1, row
        assert PREP not in out and COMPLETE not in out and PTE not in out, row
        assert REJECT not in out and FAIL in out, row
    else:
        assert mode in ("dishonest", "decoy"), row
        assert p.returncode == 35 and out.count(REJECT) == 1, row
        assert PREP not in out and COMPLETE not in out and PTE not in out, row
        assert STALE not in out and FAIL in out, row
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", default="qemu-system-x86_64")
    args = p.parse_args()
    rows = [run(args.qemu, machine, mib, mode)
            for machine, mib in (("pc", 32), ("q35", 64))
            for mode in ("hw", "stale", "dishonest", "decoy", "abort", "abort-noop",
                         "guarded", "guarded-noop", "guarded-stale", "guarded-published",
                         "recycle", "recycle-double")]
    report = {"schema": "heptakernel.cow-integrated-qemu.v1",
              "head_evidence": "exact-built-image-per-case", "positives": 2,
              "negative_controls": 22, "guarded_abort_checks": 12,
              "pmm_reclaim_reissue_cases": 2, "pmm_double_free_refusals": 2,
              "cases": rows, "status": "PASS"}
    Path("build/cow-integrated-hardware-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
