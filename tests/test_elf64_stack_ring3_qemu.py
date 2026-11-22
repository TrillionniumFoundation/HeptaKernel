#!/usr/bin/env python3
"""Independent PC/Q35 CPU-level readback of native HIA ELF64 initial stack.

This is a QEMU/assembly hardware observer, not an HIA privileged backend,
Linux execve, a user task, or user-space memory safety qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

CASES = {
    "ring3": ("HEPTAKERNEL HIA ELF64 STACK CPL3 AUXV READ VERIFIED", 45),
    "ring3-decoy": ("HEPTAKERNEL HIA ELF64 STACK CPL3 POSTWRITE DECOY OBSERVED", 35),
    "ring3-iret-stale": ("HEPTAKERNEL HIA IRET USER STACK RIP REFUSED BEFORE IRETQ", 35),
    "ring3-iret-rflags-bit0": ("HEPTAKERNEL HIA IRET RFLAGS RESERVED BIT0 REFUSED BEFORE IRETQ", 35),
}
REQUIRED = (
    "HEPTAKERNEL HIA LIVE TSS STATE VERIFIED",
    "HEPTAKERNEL HIA LIVE IDT VERIFIED",
    "HEPTAKERNEL HIA E820 VERIFIED",
    "HEPTAKERNEL HIA RESERVATIONS VERIFIED",
    "HEPTAKERNEL HIA ELF64 INITIAL STACK PHYSICAL SUFFIX VERIFIED",
    "HEPTAKERNEL HIA LIVE UPPER USER TABLE VERIFIED",
)
UNEXPECTED = (
    "HEPTAKERNEL HIA ELF64 STACK BAD PHENT REFUSED UNCHANGED",
    "HEPTAKERNEL HIA ELF64 STACK ENTRY COLLISION REFUSED UNCHANGED",
    "HEPTAKERNEL HIA ELF64 STACK PHDR COLLISION REFUSED UNCHANGED",
    "HEPTAKERNEL HIA ELF64 STACK DISHONEST NOOP DETECTED",
)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(qemu, machine, memory, mode):
    marker, expected_rc = CASES[mode]
    image = Path("build/elf-stack-" + mode + "-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(memory), "-nodefaults", "-display", "none", "-serial", "stdio",
           "-monitor", "none", "-no-reboot", "-device",
           "isa-debug-exit,iobase=0xf4,iosize=0x04", "-kernel", str(image)]
    row = {"machine": machine, "memory_mib": memory, "mode": mode,
           "image": str(image), "image_sha256": digest(image), "command": cmd,
           "status": "NOT_RUN"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        row.update(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        marker_counts = {name: p.stdout.count(value[0]) for name, value in CASES.items()}
        valid = (
            p.returncode == expected_rc
            and marker_counts[mode] == 1
            and all(marker_counts[x] == 0 for x in CASES if x != mode)
            and all(p.stdout.count(x) == 1 for x in REQUIRED)
            and all(x not in p.stdout for x in UNEXPECTED)
            and (("HEPTAKERNEL BOOT FAIL" not in p.stdout) if mode == "ring3"
                 else (p.stdout.count("HEPTAKERNEL BOOT FAIL") == 1))
        )
        row["marker_counts"] = marker_counts
        row["precondition_counts"] = {x: p.stdout.count(x) for x in REQUIRED}
        row["status"] = "PASS" if valid else "FAIL"
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", error=str(exc))
    return row

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    source = Path("src/elf64_start_stack.hepta")
    report = {
        "schema": "heptakernel.hia-elf64-stack-real-cpl3-qemu.v1",
        "candidate_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),
        "hia_source_sha256": digest(source),
        "hia_object_sha256": digest("build/elf64-start-stack.o"),
        "hia_boot_object_sha256": digest("build/elf64-start-stack-boot.o"),
        "bridge_source_sha256": digest("arch/x86_64/boot.S"),
        "test_source_sha256": digest(__file__),
        "real_cpl3_cpu_load": True,
        "native_hia_constructs_initial_stack": True,
        "non_hia_iret_and_exception_bridge": True,
        "linux_execve_implemented": False,
        "native_hia_privileged_backend": False,
        "full_linux": "HOLD",
        "runs": [],
    }
    for machine, memory in (("pc", 32), ("q35", 64)):
        for mode in CASES:
            row = run(args.qemu, machine, memory, mode)
            report["runs"].append(row)
            print("HIA_ELF64_STACK_CPL3", machine, mode, row["status"],
                  row.get("returncode"), row.get("marker_counts"))
    report["status"] = (
        "PASS" if all(x["status"] == "PASS" for x in report["runs"]) else "FAIL")
    out = Path("build/elf64-stack-cpl3-qemu-report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("HIA_ELF64_STACK_CPL3:", report["status"], len(report["runs"]))
    print("FULL_LINUX_REWRITE: HOLD")
    raise SystemExit(0 if report["status"] == "PASS" else 1)

if __name__ == "__main__":
    main()
