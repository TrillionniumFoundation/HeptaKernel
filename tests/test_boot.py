#!/usr/bin/env python3
"""Run the genuine boot image and two independently broken HIA kernels."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PASS_MARKER = "HEPTAKERNEL HIA PMM PASS"
FAIL_MARKER = "HEPTAKERNEL BOOT FAIL"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(qemu, image, machine="pc", memory="32", positive=True):
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64", "-m", memory,
           "-nodefaults", "-display", "none", "-serial", "stdio", "-monitor", "none",
           "-no-reboot", "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    record = {"image": str(image), "image_sha256": digest(image), "machine": machine,
              "memory_mib": int(memory), "positive": positive, "command": cmd}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        record.update(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        if positive:
            accepted = p.returncode == 33 and p.stdout.count(PASS_MARKER) == 1 and FAIL_MARKER not in p.stdout
        else:
            # Timeout, crash or a triple fault is not accepted as an observed
            # diagnostic. The guest must enter its explicit failure path.
            accepted = p.returncode == 35 and FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout
        record["status"] = "PASS" if accepted else "FAIL"
    except subprocess.TimeoutExpired as e:
        record.update(status="FAIL", error="QEMU timed out", stdout=str(e.stdout), stderr=str(e.stderr))
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", default="qemu-system-x86_64")
    ap.add_argument("--report", type=Path, default=Path("build/boot-report.json"))
    args = ap.parse_args()
    report = {"schema": "heptakernel.boot-tests.v1", "scope": "x86-64 TCG foundation",
              "hardware_qualification": False, "linux_compatibility": False,
              "all_kernel_code_in_hia": False,
              "source_sha256": digest("src/kernel.hepta"), "hia_object_sha256": digest("build/kernel.o"),
              "bridge_sha256": digest("arch/x86_64/boot.S"),
              "fixtures_sha256": digest("tests/boot-cases.json"), "runs": []}
    try:
        version = subprocess.run([args.qemu, "--version"], capture_output=True, text=True, timeout=10, check=True)
        report["qemu_version"] = version.stdout.splitlines()[0]
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/kernel-multiboot.elf"), machine, memory))
        for name in ("success_stub", "bounds_trap"):
            report["runs"].append(run(args.qemu, Path("build/" + name + "-multiboot.elf"), positive=False))
        report["status"] = "PASS" if all(r["status"] == "PASS" for r in report["runs"]) else "FAIL"
    except Exception as exc:
        report.update(status="FAIL", error=repr(exc))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
