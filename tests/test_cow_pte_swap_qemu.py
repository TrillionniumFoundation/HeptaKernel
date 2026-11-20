#!/usr/bin/env python3
"""Independent hardware #PF, native HIA remap and real QEMU RAM oracle."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
PTE = "HEPTAKERNEL HIA LIVE PTE VERIFIED"
MAPPED = "HEPTAKERNEL HIA COW PTE SOURCE MAPPING VERIFIED"
FAULT = "HEPTAKERNEL COW PTE REAL WRITE PROTECT FAULT OBSERVED"
SUCCESS = "HEPTAKERNEL HIA COW PTE HARDWARE REMAP AND PHYSICAL RAM VERIFIED"
STALE = "HEPTAKERNEL HIA COW PTE STALE EXPECTED OLD REJECTED"
DISHONEST = "HEPTAKERNEL HIA COW PTE DISHONEST NOOP REJECTED"
BYPASS = "HEPTAKERNEL HIA COW PTE RESTORE BYPASS REFAULT VERIFIED"
FAIL = "HEPTAKERNEL BOOT FAIL"

def probe(qemu: str, machine: str, mib: int, mode: str) -> dict:
    filename = Path(f"build/cow-pte-{mode}-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(mib), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(filename)]
    row = {"machine": machine, "memory_mib": mib, "mode": mode,
           "image": str(filename),
           "image_sha256": hashlib.sha256(filename.read_bytes()).hexdigest(),
           "command": cmd}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", stdout=str(exc.stdout), stderr=str(exc.stderr))
        raise AssertionError(json.dumps(row, sort_keys=True)) from exc
    row.update(status="COMPLETED", returncode=p.returncode,
               stdout=p.stdout, stderr=p.stderr)
    out = p.stdout
    for label in (MAP, RESERV, PTE, MAPPED, FAULT):
        assert out.count(label) == 1, json.dumps(row, sort_keys=True)
    assert all(out.count(x) <= 1 for x in (SUCCESS, STALE, DISHONEST, BYPASS))
    if mode == "hw":
        assert p.returncode == 75, json.dumps(row, sort_keys=True)
        assert out.count(SUCCESS) == 1, json.dumps(row, sort_keys=True)
        assert FAIL not in out, json.dumps(row, sort_keys=True)
        assert all(x not in out for x in (STALE, DISHONEST, BYPASS))
    elif mode == "stale":
        assert p.returncode == 35 and out.count(STALE) == 1
        assert out.count(FAIL) == 1 and SUCCESS not in out
        assert DISHONEST not in out and BYPASS not in out
    elif mode == "dishonest":
        assert p.returncode == 35 and out.count(DISHONEST) == 1
        assert out.count(FAIL) == 1 and SUCCESS not in out
        assert STALE not in out and BYPASS not in out
    elif mode == "bypass":
        assert p.returncode == 95 and out.count(BYPASS) == 1
        assert FAIL not in out and SUCCESS not in out
        assert STALE not in out and DISHONEST not in out
    return row

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", default="qemu-system-x86_64")
    args = ap.parse_args()
    cases = [probe(args.qemu, machine, mib, mode)
             for machine, mib in (("pc", 32), ("q35", 64))
             for mode in ("hw", "stale", "dishonest", "bypass")]
    report = {"schema": "heptakernel.cow-pte-qemu.v1",
              "cases": len(cases), "positives": 2, "negative_controls": 6,
              "status": "PASS", "runs": cases}
    Path("build/cow-pte-hardware-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
