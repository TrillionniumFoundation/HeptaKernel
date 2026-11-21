#!/usr/bin/env python3
"""Independent PC/Q35 hardware oracle for genuine HIA ELF page-plan + fill.

The experimental non-HIA bootstrap observes a fixed ELF64 file image. This
does not constitute an atomic snapshot, a real execve or a HIA privileged
backend. Expected refusals have unique serial markers and exact debug-exits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

E820 = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
PMM = "HEPTAKERNEL HIA PMM PASS"
GOOD = "HEPTAKERNEL HIA ELF64 NATIVE PLAN PHYSICAL FILE BSS VERIFIED"
BAD = {
    "invalid": "HEPTAKERNEL HIA ELF64 INVALID PLAN REFUSED PHYSICAL UNCHANGED",
    "noop": "HEPTAKERNEL HIA ELF64 DISHONEST PLAN NOOP DETECTED",
    "decoy": "HEPTAKERNEL HIA ELF64 POST PLAN DECOY DETECTED",
    "overlap": "HEPTAKERNEL HIA ELF64 FULL LAYOUT OVERLAP REFUSED PHYSICAL UNCHANGED",
    "layout-liar": "HEPTAKERNEL HIA ELF64 DISHONEST FULL LAYOUT ACCEPT DETECTED",
    "snapshot-mutated": "HEPTAKERNEL HIA ELF64 POST PLAN PAYLOAD MUTATION REFUSED PHYSICAL UNCHANGED",
    "snapshot-liar": "HEPTAKERNEL HIA ELF64 DISHONEST SNAPSHOT EQUALITY DETECTED",
    "stage-noop": "HEPTAKERNEL HIA ELF64 DISHONEST STAGE NO-COPY DETECTED PHYSICAL UNCHANGED",
    "stage-corrupt": "HEPTAKERNEL HIA ELF64 STAGED PAYLOAD CORRUPTION REFUSED PHYSICAL UNCHANGED",
}
FAIL = "HEPTAKERNEL BOOT FAIL"
SOURCE_ISOLATED = "HEPTAKERNEL HIA ELF64 STAGED SOURCE MUTATION ISOLATED"


def probe(qemu: str, machine: str, memory: int, mode: str) -> dict:
    image = Path(f"build/elf-plan-{mode}-multiboot.elf")
    cmd = [
        qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
        "-m", str(memory), "-nodefaults", "-display", "none",
        "-serial", "stdio", "-monitor", "none", "-no-reboot",
        "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
        "-kernel", str(image),
    ]
    completed = subprocess.run(
        cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=22, check=False,
    )
    output = completed.stdout
    expected = 33 if mode in ("hw", "source-isolated") else 35
    marker = GOOD if mode in ("hw", "source-isolated") else BAD[mode]
    assert completed.returncode == expected, (
        "unexpected debug-exit", mode, machine, completed.returncode, output[-4000:]
    )
    assert E820 in output and RESERV in output, (
        "unverified firmware memory", mode, machine, output[-4000:]
    )
    assert output.count(marker) == 1, (
        "missing unique physical oracle", mode, machine, output[-4000:]
    )
    if mode in ("hw", "source-isolated"):
        assert PMM in output and FAIL not in output
        if mode == "source-isolated":
            assert output.count(SOURCE_ISOLATED) == 1
        else:
            assert SOURCE_ISOLATED not in output
        assert not any(m in output for m in BAD.values())
    else:
        assert FAIL in output and GOOD not in output and PMM not in output
        assert all(m not in output for k, m in BAD.items() if k != mode)
    return {
        "machine": machine, "memory_mib": memory, "mode": mode,
        "status": "PASS", "exit_code": completed.returncode,
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "marker": marker,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    records = [
        probe(args.qemu, machine, memory, mode)
        for machine, memory in (("pc", 32), ("q35", 64))
        for mode in ("hw", "source-isolated", "invalid", "noop", "decoy", "overlap", "layout-liar", "snapshot-mutated", "snapshot-liar", "stage-noop", "stage-corrupt")
    ]
    report = {
        "schema": "heptakernel.elf64-page-plan-qemu.v1",
        "status": "PASS", "cases": len(records), "positive": 4,
        "negative_controls": 18, "native_hia_plan": True,
        "native_hia_full_elf_layout_gate": True,
        "full_8192_byte_negative_physical_readback": ["overlap", "layout-liar", "snapshot-mutated", "snapshot-liar", "stage-noop", "stage-corrupt"],
        "native_hia_snapshot_byte_equality": True,
        "native_hia_pre_admission_stage_copy": True,
        "stage_no_copy_forged_receipt_detected": True,
        "staged_tamper_detected_before_physical_write": True,
        "post_stage_source_mutation_isolated": True,
        "native_hia_payload_mutation_refusal": True,
        "native_hia_page_fill": True,
        "non_hia_fixture_and_independent_oracle": True,
        "authenticated_file_snapshot": False,
        "actual_linux_execve": False, "full_linux_acceptance": "HOLD",
        "cases_detail": records,
    }
    Path("build/elf-plan-hardware-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
