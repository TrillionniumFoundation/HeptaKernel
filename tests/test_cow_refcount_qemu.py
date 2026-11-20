#!/usr/bin/env python3
"""Independent QEMU observer of the genuine native HIA refcount table writes.

All calls and actual memory readbacks are inside a clearly NON-HIA single-core
test bridge. The positive sequence is share/detach/release for slots 2 and 17,
with every other byte of the 4096-byte table checked unchanged. This is NOT COW
fault handling, ownership provenance, or atomic SMP synchronization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
COW = "HEPTAKERNEL HIA COW REFCOUNT QEMU TRANSITIONS VERIFIED"
STALE = "HEPTAKERNEL HIA COW REFCOUNT STALE EXPECTED-OLD REFUSED"
OWNER = "HEPTAKERNEL HIA MULTI-ARENA OWNERSHIP VERIFIED"
PMM = "HEPTAKERNEL HIA PMM PASS"
FAIL = "HEPTAKERNEL BOOT FAIL"


def probe(qemu: str, image: Path, machine: str, memory: int, mode: str) -> dict:
    command = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
               "-m", str(memory), "-nodefaults", "-display", "none",
               "-serial", "stdio", "-monitor", "none", "-no-reboot",
               "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
               "-kernel", str(image)]
    row = {"machine": machine, "memory_mib": memory, "mode": mode,
           "image": str(image), "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
           "command": command}
    try:
        process = subprocess.run(command, text=True, capture_output=True, timeout=25)
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
    rows = []
    for machine, memory in (("pc", 32), ("q35", 64)):
        for mode in ("honest", "dishonest", "stale", "decoy"):
            name = "hw" if mode == "honest" else mode
            rows.append(probe(args.qemu, Path(f"build/cow-refcount-{name}-multiboot.elf"),
                              machine, memory, mode))
    report = {"cases": len(rows), "positive": 2, "negative_controls": 6,
              "hardware_status": "PASS", "runs": rows}
    Path("build/cow-refcount-hardware-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
