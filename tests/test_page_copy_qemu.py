#!/usr/bin/env python3
"""Independent QEMU native-HIA page-copy physical RAM readback observer.

An HIA return value or self-reported receipt never determines success.
Only the NON-HIA test bridge's complete physical source/destination oracle
is observed; its dishonest HIA and post-copy corruption images must fail.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
COPY = "HEPTAKERNEL HIA PHYSICAL PAGE COPY TWO PAIRS VERIFIED"
OWNER = "HEPTAKERNEL HIA MULTI-ARENA OWNERSHIP VERIFIED"
PMM = "HEPTAKERNEL HIA PMM PASS"
FAIL = "HEPTAKERNEL BOOT FAIL"


def probe(qemu: str, image: Path, machine: str, memory: int, mode: str) -> dict:
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(memory), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    record = {"machine": machine, "memory_mib": memory, "mode": mode,
              "image": str(image), "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
              "command": cmd}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired as exc:
        record.update(status="TIMEOUT", stdout=str(exc.stdout), stderr=str(exc.stderr))
        raise AssertionError(json.dumps(record, sort_keys=True)) from exc
    record.update(status="COMPLETED", returncode=result.returncode,
                  stdout=result.stdout, stderr=result.stderr)
    assert result.stdout.count(MAP) == 1, json.dumps(record, sort_keys=True)
    assert result.stdout.count(RESERV) == 1, json.dumps(record, sort_keys=True)
    if mode == "honest":
        assert result.returncode == 33, json.dumps(record, sort_keys=True)
        assert result.stdout.count(COPY) == 1, json.dumps(record, sort_keys=True)
        assert result.stdout.count(OWNER) == 1, json.dumps(record, sort_keys=True)
        assert result.stdout.count(PMM) == 1, json.dumps(record, sort_keys=True)
        assert FAIL not in result.stdout, json.dumps(record, sort_keys=True)
    else:
        assert result.returncode == 35, json.dumps(record, sort_keys=True)
        assert result.stdout.count(COPY) == 0, json.dumps(record, sort_keys=True)
        assert result.stdout.count(OWNER) == 0, json.dumps(record, sort_keys=True)
        assert result.stdout.count(PMM) == 0, json.dumps(record, sort_keys=True)
        assert result.stdout.count(FAIL) == 1, json.dumps(record, sort_keys=True)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    runs = []
    for machine, memory in (("pc", 32), ("q35", 64)):
        for mode in ("honest", "dishonest", "decoy", "source-decoy"):
            suffix = "hw" if mode == "honest" else mode
            image = Path(f"build/page-copy-{suffix}-multiboot.elf")
            runs.append(probe(args.qemu, image, machine, memory, mode))
    report = {"cases": len(runs), "positive": 2, "negative_controls": 6,
              "hardware_status": "PASS", "runs": runs}
    Path("build/page-copy-hardware-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
