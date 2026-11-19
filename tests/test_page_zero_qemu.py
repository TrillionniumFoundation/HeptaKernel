#!/usr/bin/env python3
"""Independent QEMU observer for HIA page-zero on four E820/PMM-owned frames."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
OWNER = "HEPTAKERNEL HIA MULTI-ARENA OWNERSHIP VERIFIED"
ZERO = "HEPTAKERNEL HIA PHYSICAL PAGE ZERO FOUR FRAMES VERIFIED"
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
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=25)
    except subprocess.TimeoutExpired as exc:
        record.update(status="TIMEOUT", stdout=str(exc.stdout), stderr=str(exc.stderr))
        raise AssertionError(json.dumps(record, sort_keys=True)) from exc
    record.update(status="COMPLETED", returncode=result.returncode,
                  stdout=result.stdout, stderr=result.stderr)
    assert result.stdout.count(MAP) == 1, json.dumps(record, sort_keys=True)
    assert result.stdout.count(RESERV) == 1, json.dumps(record, sort_keys=True)
    if mode == "honest":
        assert result.returncode == 33, json.dumps(record, sort_keys=True)
        assert result.stdout.count(ZERO) == 1, json.dumps(record, sort_keys=True)
        assert result.stdout.count(OWNER) == 1, json.dumps(record, sort_keys=True)
        assert result.stdout.count(PMM) == 1, json.dumps(record, sort_keys=True)
        assert FAIL not in result.stdout, json.dumps(record, sort_keys=True)
    else:
        assert result.returncode == 35, json.dumps(record, sort_keys=True)
        assert result.stdout.count(ZERO) == 0, json.dumps(record, sort_keys=True)
        assert result.stdout.count(OWNER) == 0, json.dumps(record, sort_keys=True)
        assert result.stdout.count(PMM) == 0, json.dumps(record, sort_keys=True)
        assert result.stdout.count(FAIL) == 1, json.dumps(record, sort_keys=True)
    return record

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    output = []
    for machine, memory in (("pc", 32), ("q35", 64)):
        for mode in ("honest", "dishonest", "decoy"):
            image = Path(f"build/page-zero-{ 'hw' if mode == 'honest' else mode }-multiboot.elf")
            output.append(probe(args.qemu, image, machine, memory, mode))
    print(json.dumps({"cases": len(output), "positive": 2, "negative_controls": 4,
                      "hardware_status": "PASS", "runs": output}, sort_keys=True))

if __name__ == "__main__":
    main()
