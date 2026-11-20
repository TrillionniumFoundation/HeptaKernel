#!/usr/bin/env python3
"""Independent QEMU oracle for original native HIA ELF file/BSS physical fill.

Test-only, non-HIA Multiboot/E820/PMM choreography is not Linux execve, an
ELF loader, an authenticated mapping capability or a privileged HIA backend.
Negative cases require their unique hardware readback/refusal markers and
expected QEMU debug-exit code. A generic crash or timeout never passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
GOOD = "HEPTAKERNEL HIA ELF64 PMM PHYSICAL PAGE FILE BSS VERIFIED"
BAD = {
    "truncated": "HEPTAKERNEL HIA ELF64 TRUNCATED REFUSED PHYSICAL UNCHANGED",
    "noop": "HEPTAKERNEL HIA ELF64 DISHONEST NOOP PHYSICAL MISMATCH DETECTED",
    "decoy": "HEPTAKERNEL HIA ELF64 POST-CALL PHYSICAL DECOY DETECTED",
}
FAIL = "HEPTAKERNEL BOOT FAIL"
PMM = "HEPTAKERNEL HIA PMM PASS"


def probe(qemu: str, image: Path, machine: str, mem: int, mode: str) -> dict:
    args = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
            "-m", str(mem), "-nodefaults", "-display", "none",
            "-serial", "stdio", "-monitor", "none", "-no-reboot",
            "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
            "-kernel", str(image)]
    observed = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=22, check=False)
    out = observed.stdout
    expect = 33 if mode == "hw" else 35
    marker = GOOD if mode == "hw" else BAD[mode]
    assert observed.returncode == expect, (
        "QEMU unexpected status", mode, machine, observed.returncode, out[-5000:])
    assert MAP in out and RESERV in out, (
        "firmware/physical admission missing", mode, machine, out[-5000:])
    assert out.count(marker) == 1, ("missing exact HIA physical oracle", mode,
                                    machine, out[-5000:])
    if mode == "hw":
        assert PMM in out and FAIL not in out, ("honest boot failed", out[-5000:])
        assert not any(m in out for m in BAD.values())
    else:
        assert FAIL in out and PMM not in out and GOOD not in out, (
            "negative mode incorrectly passed", mode, out[-5000:])
        assert all(m not in out for key, m in BAD.items() if key != mode)
    return {"machine": machine, "memory_mib": mem, "mode": mode,
            "status": "PASS", "exit_code": observed.returncode,
            "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "oracle_marker": marker}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    opt = parser.parse_args()
    records = []
    for machine, mem in (("pc", 32), ("q35", 64)):
        for mode in ("hw", "truncated", "noop", "decoy"):
            image = Path(f"build/elf-page-{mode}-multiboot.elf")
            records.append(probe(opt.qemu, image, machine, mem, mode))
    report = {"schema": "heptakernel.elf-page-qemu.v1",
              "status": "PASS", "cases": len(records),
              "positive": 2, "negative_controls": 6,
              "source": "src/elf64_page_fill.hepta",
              "native_hia_page_fill": True,
              "firmware_bridge_and_oracle_non_hia": True,
              "actual_elf_loader": False,
              "full_linux_acceptance": "HOLD", "cases_detail": records}
    Path("build/elf-page-hardware-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
