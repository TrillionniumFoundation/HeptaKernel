#!/usr/bin/env python3
"""Independent real-QEMU observer of native HIA PMM/PTE COW frame binding.

The GNU assembly boot harness remains NON-HIA; this test does not claim
CR3 authenticated provenance, linearizable ownership or SMP safety.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
LIVE = "HEPTAKERNEL HIA COW FRAME BINDING LIVE PMM PTE VERIFIED"
BITMAP = "HEPTAKERNEL HIA COW FRAME BINDING BITMAP REFUSED UNCHANGED"
STALE = "HEPTAKERNEL HIA COW FRAME BINDING STALE PTE REFUSED UNCHANGED"
NOOP = "HEPTAKERNEL HIA COW FRAME BINDING DISHONEST ACCEPT DETECTED"
FAULT = "HEPTAKERNEL COW PTE REAL WRITE PROTECT FAULT OBSERVED"
PREP = "HEPTAKERNEL HIA COW INTEGRATED PAGE COPY AND COUNTS VERIFIED"
COMPLETE = "HEPTAKERNEL HIA COW INTEGRATED PF COPY REFCOUNT PTE VERIFIED"
PTE = "HEPTAKERNEL HIA COW PTE HARDWARE REMAP AND PHYSICAL RAM VERIFIED"
FAIL = "HEPTAKERNEL BOOT FAIL"

MARKERS = {"hw": LIVE, "pte-stale": STALE, "bitmap": BITMAP, "noop": NOOP}


def run(qemu: str, machine: str, memory: int, mode: str) -> dict:
    image = Path(f"build/cow-binding-{mode}-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(memory), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    row = {"machine": machine, "memory_mib": memory, "mode": mode,
           "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
           "command": cmd}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", stdout=str(exc.stdout), stderr=str(exc.stderr))
        raise AssertionError(json.dumps(row, sort_keys=True)) from exc
    row.update(status="COMPLETED", returncode=p.returncode,
               stdout=p.stdout, stderr=p.stderr)
    out = p.stdout
    for marker in (MAP, RESERV, MARKERS[mode]):
        assert out.count(marker) == 1, row
    for other_mode, marker in MARKERS.items():
        if other_mode != mode:
            assert marker not in out, row
    if mode == "hw":
        assert p.returncode == 75 and FAIL not in out, row
        for marker in (FAULT, PREP, COMPLETE, PTE):
            assert out.count(marker) == 1, row
    else:
        assert p.returncode == 35 and out.count(FAIL) == 1, row
        for marker in (FAULT, PREP, COMPLETE, PTE):
            assert marker not in out, row
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    rows = [run(args.qemu, machine, memory, mode)
            for machine, memory in (("pc", 32), ("q35", 64))
            for mode in MARKERS]
    report = {"schema": "heptakernel.cow-frame-binding-qemu.v1",
              "cases": rows, "positive": 2, "negative_controls": 6,
              "status": "PASS"}
    Path("build/cow-frame-binding-qemu-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
