#!/usr/bin/env python3
"""Independent QEMU physical-byte observation for locked HIA ELF64 initial stack."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

CASES = {
    "hw": ("HEPTAKERNEL HIA ELF64 INITIAL STACK PHYSICAL SUFFIX VERIFIED", 33, True),
    "bad-phent": ("HEPTAKERNEL HIA ELF64 STACK BAD PHENT REFUSED UNCHANGED", 35, False),
    "entry-collision": ("HEPTAKERNEL HIA ELF64 STACK ENTRY COLLISION REFUSED UNCHANGED", 35, False),
    "phdr-collision": ("HEPTAKERNEL HIA ELF64 STACK PHDR COLLISION REFUSED UNCHANGED", 35, False),
    "liar": ("HEPTAKERNEL HIA ELF64 STACK DISHONEST NOOP DETECTED", 35, False),
    "decoy": ("HEPTAKERNEL HIA ELF64 STACK POSTWRITE DECOY DETECTED", 35, False),
}
PRECONDITIONS = ("HEPTAKERNEL HIA LIVE TSS STATE VERIFIED",
                 "HEPTAKERNEL HIA LIVE IDT VERIFIED",
                 "HEPTAKERNEL HIA E820 VERIFIED",
                 "HEPTAKERNEL HIA RESERVATIONS VERIFIED",
                 "HEPTAKERNEL HIA LIVE PTE VERIFIED",
                 "HEPTAKERNEL HIA ARENA ROUTER VERIFIED")

def hashfile(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(qemu, platform, ram, label):
    marker, expected_rc, positive = CASES[label]
    image = Path("build/elf-stack-" + label + "-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", platform, "-cpu", "qemu64",
           "-m", str(ram), "-nodefaults", "-display", "none", "-serial", "stdio",
           "-monitor", "none", "-no-reboot", "-device",
           "isa-debug-exit,iobase=0xf4,iosize=0x04", "-kernel", str(image)]
    result = {"machine": platform, "memory_mib": ram, "mode": label,
              "image": str(image), "image_sha256": hashfile(image),
              "command": cmd, "status": "NOT_RUN"}
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=25)
        result.update(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        markers = {key: p.stdout.count(spec[0]) for key, spec in CASES.items()}
        expected = all(v == (1 if key == label else 0)
                       for key, v in markers.items())
        valid_preconditions = all(p.stdout.count(x) == 1 for x in PRECONDITIONS)
        normal = ("HEPTAKERNEL HIA PMM PASS" in p.stdout
                  and "HEPTAKERNEL BOOT FAIL" not in p.stdout)
        reject = ("HEPTAKERNEL BOOT FAIL" in p.stdout
                  and "HEPTAKERNEL HIA PMM PASS" not in p.stdout)
        result["marker_counts"] = markers
        result["status"] = ("PASS" if expected and valid_preconditions
                            and p.returncode == expected_rc
                            and (normal if positive else reject) else "FAIL")
    except subprocess.TimeoutExpired as exc:
        result.update(status="TIMEOUT", error=str(exc))
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qemu", default="qemu-system-x86_64")
    args = p.parse_args()
    report = {
        "schema": "heptakernel.hia-elf64-stack-physical-qemu.v1",
        "source_sha256": hashfile("src/elf64_start_stack.hepta"),
        "native_object_sha256": hashfile("build/elf64-start-stack.o"),
        "boot_native_object_sha256": hashfile("build/elf64-start-stack-boot.o"),
        "dishonest_source_sha256": hashfile("tests/negative/elf64_start_stack_noop.hepta"),
        "dishonest_object_sha256": hashfile("build/elf64-start-stack-liar.o"),
        "bridge_source_sha256": hashfile("arch/x86_64/boot.S"),
        "full_linux": "HOLD",
        "real_execve": False, "hia_privilege_backend": False,
        "cpu_hardware_execution_of_initial_stack": False,
        "runs": []
    }
    for platform, ram in (("pc", 32), ("q35", 64)):
        for label in CASES:
            report["runs"].append(run(args.qemu, platform, ram, label))
    report["status"] = ("PASS" if all(x["status"] == "PASS" for x in report["runs"])
                        else "FAIL")
    target = Path("build/elf64-stack-physical-qemu-report.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    for x in report["runs"]:
        print("HIA_ELF64_STACK_QEMU", x["machine"], x["mode"], x["status"],
              x.get("returncode"), x.get("marker_counts", {}))
    print("HIA_ELF64_STACK_PHYSICAL:", report["status"], len(report["runs"]))
    print("FULL_LINUX_REWRITE: HOLD")
    raise SystemExit(0 if report["status"] == "PASS" else 1)

if __name__ == "__main__":
    main()
