#!/usr/bin/env python3
"""Independent QEMU oracle: native HIA PMM bitmap on real COW physical RAM."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RES = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
BINDING = "HEPTAKERNEL HIA COW FRAME BINDING LIVE PMM PTE VERIFIED"
FAULT = "HEPTAKERNEL COW PTE REAL WRITE PROTECT FAULT OBSERVED"
PREP = "HEPTAKERNEL HIA COW INTEGRATED PAGE COPY AND COUNTS VERIFIED"
COMPLETE = "HEPTAKERNEL HIA COW INTEGRATED PF COPY REFCOUNT PTE VERIFIED"
PTE = "HEPTAKERNEL HIA COW PTE HARDWARE REMAP AND PHYSICAL RAM VERIFIED"
FAIL = "HEPTAKERNEL BOOT FAIL"
MODES = {
    "hw": "HEPTAKERNEL HIA PMM LIVE COMPLETE BITMAP VERIFIED",
    "free-stale": "HEPTAKERNEL HIA PMM STALE FREE COUNT REFUSED UNCHANGED",
    "reserved-missing": "HEPTAKERNEL HIA PMM MISSING RESERVED BIT REFUSED UNCHANGED",
    "tail-dirty": "HEPTAKERNEL HIA PMM TAIL BIT REFUSED UNCHANGED",
    "noop": "HEPTAKERNEL HIA PMM DISHONEST ACCEPT DETECTED",
}

def run(qemu, machine, memory, mode):
    path = Path(f"build/pmm-bitmap-{mode}-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(memory), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(path)]
    row = {"machine": machine, "memory_mib": memory, "mode": mode,
           "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
           "command": cmd}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", stdout=str(exc.stdout), stderr=str(exc.stderr))
        raise AssertionError(json.dumps(row, sort_keys=True)) from exc
    row.update(status="COMPLETED", returncode=p.returncode,
               stdout=p.stdout, stderr=p.stderr)
    out = p.stdout
    for marker in (MAP, RES, MODES[mode]):
        assert out.count(marker) == 1, row
    for other, marker in MODES.items():
        if other != mode:
            assert marker not in out, row
    if mode == "hw":
        assert p.returncode == 75 and FAIL not in out, row
        for marker in (BINDING, FAULT, PREP, COMPLETE, PTE):
            assert out.count(marker) == 1, row
    else:
        assert p.returncode == 35 and out.count(FAIL) == 1, row
        for marker in (BINDING, FAULT, PREP, COMPLETE, PTE):
            assert marker not in out, row
    return row

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    rows = [run(args.qemu, m, mem, mode)
            for m, mem in (("pc", 32), ("q35", 64)) for mode in MODES]
    report = {"schema": "heptakernel.pmm-bitmap-live-qemu.v1",
              "cases": rows, "positive": 2, "negative_controls": 8,
              "status": "PASS"}
    Path("build/pmm-bitmap-hardware-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
