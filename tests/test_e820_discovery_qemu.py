#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Positive-only native-discovery, exact admission, and PMM guest handoff."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

BUILD = Path("build")
MAP = "HEPTAKERNEL HIA E820 VERIFIED"
RESERV = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
PREFIX = "HEPTAKERNEL HIA E820 PHYSICAL PMM "
DEFAULT = "HEPTAKERNEL HIA PMM PASS"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_range(path):
    out = subprocess.check_output(["objdump", "-h", path], text=True)
    rows = [x.split() for x in out.splitlines() if x.split()[1:2] == [".text"]]
    assert len(rows) == 1, (path, rows)
    _, _, size, addr, _, offset, *_ = rows[0]
    return int(addr, 16), int(offset, 16), int(size, 16)


def symbol(path, name):
    out = subprocess.check_output(["nm", "-n", path], text=True)
    rows = [x.split() for x in out.splitlines() if x.split()[-1:] == [name]]
    assert len(rows) == 1, (path, name, rows)
    assert rows[0][1] == "T", rows
    return int(rows[0][0], 16)


def verify_loaded_hia(image, discovered):
    names = {
        "kernel.o": "f0",
        "e820-boot.o": "e820_f0",
        "reservation-boot.o": "reservation_f0",
    }
    if discovered:
        names["e820-discovery-native.o"] = "e820_discovery_f0"
    addr, offset, size = text_range(image)
    report = {}
    guest = image.read_bytes()
    for obj_name, name in names.items():
        obj = BUILD / obj_name
        obj_addr, obj_off, length = text_range(obj)
        assert length > 0 and symbol(obj, name) == obj_addr
        code = obj.read_bytes()[obj_off:obj_off + length]
        assert len(code) == length
        location = symbol(image, name) - addr
        assert 0 <= location <= size - length
        assert code == guest[offset + location:offset + location + length], name
        report[name] = {"object_sha256": digest(obj), "bytes": length,
                        "text_sha256": hashlib.sha256(code).hexdigest()}
    return report


def run(qemu, machine, memory, image, expected):
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64",
           "-m", str(memory), "-nodefaults", "-display", "none",
           "-serial", "stdio", "-monitor", "none", "-no-reboot",
           "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    record = {"command": cmd, "machine": machine, "memory_mib": memory,
              "guest_sha256": digest(image), "returncode": result.returncode,
              "stdout": result.stdout, "stderr": result.stderr}
    lines = result.stdout.splitlines()
    assert result.returncode == 33 and not result.stderr, record
    assert not any("HEPTAKERNEL BOOT FAIL" in x for x in lines), record
    assert lines.count(MAP) == lines.count(RESERV) == 1, record
    if expected is None:
        assert lines.count(DEFAULT) == 1 and not any(x.startswith(PREFIX) for x in lines), record
        end = DEFAULT
    else:
        base, allocated = expected
        end = f"{PREFIX}base={base:016x} allocated={allocated:016x}"
        assert lines.count(end) == 1 and DEFAULT not in lines, record
        record.update(selected_base=base, allocated_start=allocated, allocated_pages=2)
    assert lines.index(MAP) < lines.index(RESERV) < lines.index(end), record
    record.update(loaded_hia=verify_loaded_hia(image, expected is not None), status="PASS")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    records = []
    for machine, memory in (("pc", 32), ("q35", 64)):
        for variant, filename, expected in (
            ("default", "kernel-multiboot.elf", None),
            ("plain", "e820-discovery-plain-multiboot.elf", (0x400000, 0x401000)),
            ("reserved", "e820-discovery-reserved-multiboot.elf", (0x500000, 0x501000)),
        ):
            record = run(args.qemu, machine, memory, BUILD / filename, expected)
            record["variant"] = variant
            records.append(record)
    report = {"schema": "heptakernel.e820-discovery-qemu.v1", "status": "PASS",
              "full_linux_acceptance": "HOLD", "cases": len(records),
              "discovery_cases": 4, "default_cases": 2, "runs": records,
              "qemu_version": subprocess.check_output([args.qemu, "--version"], text=True).splitlines()[0],
              "source_sha256": {str(p): digest(p) for p in
                                (Path("src/e820_find_arena.hepta"), Path("src/e820_region.hepta"),
                                 Path("src/reservation_gate.hepta"), Path("src/kernel.hepta"),
                                 Path("arch/x86_64/boot.S"), Path("arch/x86_64/e820_discovery_fixture.inc"))}}
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    # Remove no existing successful record until the complete new report is ready.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=BUILD, delete=False) as tmp:
        tmp.write(payload)
    Path(tmp.name).replace(BUILD / "e820-discovery-qemu-report.json")
    print(f"Native E820 discovery/QEMU PASS: {len(records)}/{len(records)}")


if __name__ == "__main__":
    main()
