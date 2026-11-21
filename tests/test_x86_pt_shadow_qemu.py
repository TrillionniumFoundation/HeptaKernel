#!/usr/bin/env python3
"""Independent QEMU hardware oracle for original Core v8 HIA offline shadow PTE builder."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

CASES = {
    "hw": ("HEPTAKERNEL HIA OFFLINE PT SHADOW HARDWARE VERIFIED", 33),
    "stale": ("HEPTAKERNEL HIA OFFLINE PT SHADOW STALE SECOND REFUSED UNCHANGED", 35),
    "liar": ("HEPTAKERNEL HIA OFFLINE PT SHADOW DISHONEST NOOP DETECTED", 35),
    "tamper": ("HEPTAKERNEL HIA OFFLINE PT SHADOW POSTBUILD TAMPER DETECTED", 35),
}
MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RES = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
BASELINE_DONE = "HEPTAKERNEL HIA PMM PASS"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def section(path, output):
    subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                    str(Path(path).resolve()), str(output)], check=True)
    return output.read_bytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    report = {
        "schema": "heptakernel.hia-pt-shadow-hardware.v1",
        "scope": "single-owner QEMU guest RAM offline shadow then non-HIA single PDE publish",
        "native_hia": True, "linux_full_acceptance": "HOLD",
        "atomic_publish": False, "smp_shootdown": False,
        "hia_privileged_backend": False, "source_ownership_proven": False,
        "source_sha256": sha("src/x86_pt_pair_shadow.hepta"),
        "original_object_sha256": sha("build/x86-pt-pair-shadow.o"),
        "boot_symbol_object_sha256": sha("build/pt-shadow-boot.o"),
        "dishonest_object_sha256": sha("build/x86-pt-pair-shadow-unsafe.o"),
        "bridge_sha256": sha("arch/x86_64/boot.S"),
        "runs": [],
    }
    try:
        with tempfile.TemporaryDirectory() as temp:
            tmp = Path(temp)
            original = section("build/x86-pt-pair-shadow.o", tmp / "original")
            boot = section("build/pt-shadow-boot.o", tmp / "boot")
            dishonest = section("build/x86-pt-pair-shadow-unsafe.o", tmp / "dishonest")
            dishonest_boot = section("build/pt-shadow-unsafe-boot.o", tmp / "dishonest-boot")
            assert original and dishonest
            assert original == boot and dishonest == dishonest_boot, "HIA boot .text mismatch"
            report["native_text_sha256"] = hashlib.sha256(original).hexdigest()
            report["dishonest_text_sha256"] = hashlib.sha256(dishonest).hexdigest()
            for mode in CASES:
                native = dishonest if mode == "liar" else original
                linked = section(f"build/pt-shadow-{mode}.elf", tmp / ("linked-" + mode))
                assert linked.count(native) == 1, f"{mode}: HIA .text not unique in linked image"
                report[mode + "_linked_native_bytes"] = "MATCH"
        version = subprocess.run([args.qemu, "--version"], text=True,
                                 capture_output=True, check=True, timeout=10)
        report["qemu_version"] = version.stdout.splitlines()[0]
        for machine, memory in (("pc", 32), ("q35", 64)):
            for mode, (marker, expected_exit) in CASES.items():
                image = Path(f"build/pt-shadow-{mode}-multiboot.elf")
                cmd = [args.qemu, "-accel", "tcg", "-machine", machine, "-cpu",
                       "qemu64", "-m", str(memory), "-nodefaults",
                       "-display", "none", "-serial", "stdio", "-monitor", "none",
                       "-no-reboot", "-device",
                       "isa-debug-exit,iobase=0xf4,iosize=0x04", "-kernel", str(image)]
                row = {"mode": mode, "machine": machine, "memory_mib": memory,
                       "image": str(image), "image_sha256": sha(image), "command": cmd}
                try:
                    process = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                    row.update(returncode=process.returncode,
                               stdout=process.stdout, stderr=process.stderr)
                    markers = [k for k, (v, _) in CASES.items() if process.stdout.count(v) == 1]
                    ok = (process.returncode == expected_exit and markers == [mode]
                          and process.stdout.count(MAP) == 1
                          and process.stdout.count(RES) == 1
                          and BASELINE_DONE not in process.stdout)
                    row["status"] = "PASS" if ok else "FAIL"
                except subprocess.TimeoutExpired as exc:
                    row.update(status="TIMEOUT", error=str(exc))
                report["runs"].append(row)
        report["status"] = ("PASS" if len(report["runs"]) == 8
                            and all(r["status"] == "PASS" for r in report["runs"])
                            else "FAIL")
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = repr(exc)
    Path("build").mkdir(exist_ok=True)
    Path("build/x86-pt-shadow-qemu-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
