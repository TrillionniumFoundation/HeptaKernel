#!/usr/bin/env python3
"""QEMU CPL0 state fed to genuine native HIA CR3 predicate, plus dishonest HIA."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

VALID = "HEPTAKERNEL HIA CR3 LIVE CPU SNAPSHOT VERIFIED"
BYPASS = "HEPTAKERNEL HIA CR3 DISHONEST BYPASS DETECTED"
FAIL = "HEPTAKERNEL BOOT FAIL"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def section(path, output):
    subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                    str(path), str(output)], check=True, capture_output=True)
    result = output.read_bytes()
    assert result, f"empty native text in {path}"
    return result


def verify_source_object_identity():
    with tempfile.TemporaryDirectory(prefix="cr3-hardware-bytes-") as tmp:
        p, q = Path(tmp) / "p", Path(tmp) / "q"
        hia = section("build/x86-cr3-gate.o", p)
        boot = section("build/cr3-boot.o", q)
        assert hia == boot, "HIA native text changed in QEMU boot object"
        dishonest = section("build/cr3-allow-all.o", p)
        bad_boot = section("build/cr3-unsafe-boot.o", q)
        assert dishonest == bad_boot, "dishonest HIA native bytes changed"
    return {"native_hia_text_sha256": hashlib.sha256(hia).hexdigest(),
            "dishonest_hia_text_sha256": hashlib.sha256(dishonest).hexdigest()}


def run(qemu, kind, machine, memory):
    image = Path(f"build/cr3-{kind}-multiboot.elf")
    command = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
               "-m", str(memory), "-nodefaults", "-display", "none",
               "-serial", "stdio", "-monitor", "none", "-no-reboot",
               "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
               "-kernel", str(image)]
    row = {"kind": kind, "machine": machine, "memory_mib": memory,
           "image_sha256": sha(image), "command": command, "status": "FAIL"}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        row.update(returncode=result.returncode, stdout=result.stdout,
                   stderr=result.stderr)
        expected = VALID if kind == "live" else BYPASS
        unwanted = BYPASS if kind == "live" else VALID
        if (result.returncode == (97 if kind == "live" else 35)
                and result.stdout.count(expected) == 1
                and unwanted not in result.stdout and FAIL not in result.stdout):
            row["status"] = "PASS"
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", error=repr(exc))
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    report = {"schema": "heptakernel.hia-cr3-qemu-sampled.v1", "status": "FAIL",
              "real_cpu_state_sampled": True, "privileged_sampler_is_hia": False,
              "hia_executes_mov_cr3": False, "physical_root_authenticated": False,
              "linux_full_acceptance": "HOLD", "runs": []}
    try:
        report.update(verify_source_object_identity())
        for machine, memory in (("pc", 32), ("q35", 64)):
            for kind in ("live", "unsafe"):
                report["runs"].append(run(args.qemu, kind, machine, memory))
        if report["runs"] and all(x["status"] == "PASS" for x in report["runs"]):
            report["status"] = "PASS"
    except Exception as exc:
        report["error"] = repr(exc)
    Path("build/cr3-hardware-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
