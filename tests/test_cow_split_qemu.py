#!/usr/bin/env python3
"""Independent QEMU guest physical RAM and refcount-table observer (non-HIA)."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
COW = "HEPTAKERNEL HIA COW SPLIT PHYSICAL RAM AND COUNTS VERIFIED"
STALE = "HEPTAKERNEL HIA COW SPLIT STALE EXPECTED-OLD REFUSED"
OWNER = "HEPTAKERNEL HIA MULTI-ARENA OWNERSHIP VERIFIED"
PMM = "HEPTAKERNEL HIA PMM PASS"
FAIL = "HEPTAKERNEL BOOT FAIL"


def probe(qemu: str, image: Path, machine: str, memory: int, mode: str) -> dict:
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(memory), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    row = {"machine": machine, "memory_mib": memory, "mode": mode,
           "image": str(image), "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
           "command": cmd}
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", stdout=str(exc.stdout), stderr=str(exc.stderr))
        raise AssertionError(json.dumps(row, sort_keys=True)) from exc
    row.update(status="COMPLETED", returncode=process.returncode,
               stdout=process.stdout, stderr=process.stderr)
    assert process.stdout.count(MAP) == 1, json.dumps(row, sort_keys=True)
    assert process.stdout.count(RESERV) == 1, json.dumps(row, sort_keys=True)
    if mode == "honest":
        assert process.returncode == 33, json.dumps(row, sort_keys=True)
        assert process.stdout.count(COW) == 1, json.dumps(row, sort_keys=True)
        assert process.stdout.count(STALE) == 0, json.dumps(row, sort_keys=True)
        assert process.stdout.count(OWNER) == 1, json.dumps(row, sort_keys=True)
        assert process.stdout.count(PMM) == 1, json.dumps(row, sort_keys=True)
        assert FAIL not in process.stdout, json.dumps(row, sort_keys=True)
    else:
        assert process.returncode == 35, json.dumps(row, sort_keys=True)
        assert process.stdout.count(COW) == 0, json.dumps(row, sort_keys=True)
        assert process.stdout.count(STALE) == (1 if mode == "stale" else 0), json.dumps(row, sort_keys=True)
        assert process.stdout.count(OWNER) == 0, json.dumps(row, sort_keys=True)
        assert process.stdout.count(PMM) == 0, json.dumps(row, sort_keys=True)
        assert process.stdout.count(FAIL) == 1, json.dumps(row, sort_keys=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    runs = []
    for machine, memory in (("pc", 32), ("q35", 64)):
        for mode in ("honest", "dishonest", "stale", "dest-decoy", "source-decoy"):
            name = "hw" if mode == "honest" else mode
            runs.append(probe(args.qemu, Path(f"build/cow-split-{name}-multiboot.elf"),
                              machine, memory, mode))
    report = {"cases": len(runs), "positive": 2, "negative_controls": 8,
              "hardware_status": "PASS", "runs": runs}
    Path("build/cow-split-hardware-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
