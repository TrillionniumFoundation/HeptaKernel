#!/usr/bin/env python3
"""Independent QEMU observer for genuine native HIA dual-zone PMM claims.

Tests run the *original selfhost_elf* object in an isolated x86-64 guest and
validate the 14 claimed physical pages with a full-page adversarial scan.
The assembly bridge is a NON-HIA observer, not an allocator implementation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

MARKERS = {
    "hw": "HEPTAKERNEL HIA DUAL PMM PHYSICAL PAGES AND TWO-ZONE EXHAUSTION VERIFIED",
    "stale": "HEPTAKERNEL HIA DUAL PMM STALE FREE REFUSED UNCHANGED",
    "liar": "HEPTAKERNEL HIA DUAL PMM DISHONEST SUCCESS DETECTED",
    "decoy": "HEPTAKERNEL HIA DUAL PMM POSTCLAIM RAM DECOY DETECTED",
}
PRECONDITIONS = (
    "HEPTAKERNEL HIA E820 VERIFIED",
    "HEPTAKERNEL HIA RESERVATIONS VERIFIED",
)
FAIL = "HEPTAKERNEL BOOT FAIL"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(qemu, machine, mib, mode):
    path = Path("build/dual-" + mode + "-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(mib), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(path)]
    row = {"machine": machine, "memory_mib": mib, "mode": mode,
           "image": str(path), "image_sha256": sha(path), "command": cmd,
           "status": "NOT_RUN"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        row.update(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        markers = {name: p.stdout.count(value) for name, value in MARKERS.items()}
        preconditions = {value: p.stdout.count(value) for value in PRECONDITIONS}
        normal = mode == "hw"
        row["marker_counts"] = markers
        row["precondition_counts"] = preconditions
        valid = (all(v == 1 for v in preconditions.values())
                 and all(count == (1 if label == mode else 0)
                         for label, count in markers.items())
                 and p.returncode == (33 if normal else 35)
                 and p.stdout.count(FAIL) == (0 if normal else 1))
        row["status"] = "PASS" if valid else "FAIL"
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", stdout=repr(exc.stdout),
                   stderr=repr(exc.stderr), error=str(exc))
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    report = {
        "schema": "heptakernel.pmm-dual-real-physical-qemu.v1",
        "native_source_sha256": sha("src/pmm_dual_claim.hepta"),
        "native_object_sha256": sha("build/pmm-dual-claim.o"),
        "renamed_boot_object_sha256": sha("build/pmm-dual-claim-boot.o"),
        "dishonest_hia_source_sha256": sha(
            "tests/negative/pmm_dual_claim_allow_all.hepta"),
        "dishonest_hia_object_sha256": sha("build/pmm-dual-claim-liar.o"),
        "assembly_observer_sha256": sha("arch/x86_64/boot.S"),
        "test_source_sha256": sha("tests/test_pmm_dual_claim_qemu.py"),
        "full_linux": "HOLD", "hia_privileged_backend": False,
        "smp_atomic": False, "trusted_ownership": False, "runs": [],
        "status": "NOT_RUN",
    }
    try:
        for platform, ram in (("pc", 32), ("q35", 64)):
            for mode in MARKERS:
                row = run(args.qemu, platform, ram, mode)
                report["runs"].append(row)
                print("HIA_DUAL_PMM_QEMU", platform, mode, row["status"],
                      row.get("returncode"), flush=True)
        report["status"] = ("PASS" if len(report["runs"]) == 8
                            and all(x["status"] == "PASS" for x in report["runs"])
                            else "FAIL")
    except BaseException as exc:
        report["status"], report["unexpected_error"] = "FAIL", repr(exc)
        raise
    finally:
        target = Path("build/pmm-dual-physical-qemu-report.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print("HIA_DUAL_PMM_PHYSICAL:", report["status"],
              len(report["runs"]), flush=True)
        print("FULL_LINUX_REWRITE: HOLD", flush=True)
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
