#!/usr/bin/env python3
"""Independent QEMU evaluator for real-CR3 HIA root scan and negative controls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

MARKERS = {
    "live": "HEPTAKERNEL HIA LIVE CR3 ROOT PAGE VERIFIED",
    "unsafe": "HEPTAKERNEL HIA CR3 ROOT UNSAFE ACCEPT DETECTED",
    "spoof": "HEPTAKERNEL HIA CR3 ROOT SPOOF REFUSED BY OBSERVER",
}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def text_bytes(path, out):
    subprocess.run(["objcopy", "-O", "binary", "--only-section=.text", str(path),
                    str(out)], check=True, capture_output=True)
    result = out.read_bytes()
    assert result, f"empty machine text: {path}"
    return result

def verify_identity():
    with tempfile.TemporaryDirectory(prefix="root-qemu-") as directory:
        p, q = Path(directory) / "a", Path(directory) / "b"
        native = text_bytes("build/x86-cr3-root.o", p)
        bridge = text_bytes("build/root-native-boot.o", q)
        assert native == bridge, "native HIA machine bytes differ in boot"
        unsafe = text_bytes("build/x86-cr3-root-unsafe.o", p)
        unsafe_bridge = text_bytes("build/root-unsafe-native-boot.o", q)
        assert unsafe == unsafe_bridge, "negative control bytes differ"
    return {"native_text_sha256": hashlib.sha256(native).hexdigest(),
            "unsafe_text_sha256": hashlib.sha256(unsafe).hexdigest(),
            "source_sha256": sha("src/x86_cr3_root.hepta")}

def boot(qemu, kind, machine, memory):
    image = Path(f"build/root-{kind}-multiboot.elf")
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(memory), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    row = {"kind": kind, "machine": machine, "memory_mib": memory,
           "image_sha256": sha(image), "command": cmd, "status": "FAIL"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        row.update(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        if (p.returncode == (97 if kind == "live" else 35)
                and p.stdout.count(MARKERS[kind]) == 1
                and not any(marker in p.stdout for k, marker in MARKERS.items()
                            if k != kind)
                and "HEPTAKERNEL BOOT FAIL" not in p.stdout):
            row["status"] = "PASS"
    except subprocess.TimeoutExpired as exc:
        row.update(status="TIMEOUT", error=repr(exc))
    return row

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    qemu = parser.parse_args().qemu
    report = {
        "schema": "heptakernel.hia-cr3-root-hardware.v1",
        "status": "FAIL", "live_cr3_read": True, "native_hia_reads_root_ram": True,
        "privileged_reader_is_hia": False, "spoof_rejected_by_non_hia": True,
        "authenticated_snapshot": False, "smp_safe": False,
        "full_acceptance": "HOLD", "runs": []
    }
    try:
        report.update(verify_identity())
        for machine, ram in (("pc", 32), ("q35", 64)):
            for kind in ("live", "unsafe", "spoof"):
                report["runs"].append(boot(qemu, kind, machine, ram))
        if len(report["runs"]) == 6 and all(x["status"] == "PASS" for x in report["runs"]):
            report["status"] = "PASS"
    except Exception as exc:
        report["error"] = repr(exc)
    Path("build/cr3-root-hardware-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)

if __name__ == "__main__":
    main()
