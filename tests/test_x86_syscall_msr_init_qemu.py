#!/usr/bin/env python3
"""Independent CPL3 SYSCALL oracle for real HIA ordered syscall MSR initialization."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/x86_syscall_msr_init.hepta"
BOOT = ROOT / "tests/fixtures/x86_syscall_msr_init.S"
LINKER = ROOT / "tests/fixtures/x86_syscall_msr_init.ld"
COMPILER_SHA = "05071e2abb7bb74982cdf8d67a58a8c16b7226ba17d4d65cd172135e90b77cb6"
COMPILER_SOURCE_SHA = "51617211447450e15bf00c875fa6b59276942f6751cd909ec3323bf14ddd85ef"


def digest(raw):
    return sha256(raw).hexdigest()


def run(argv, **kw):
    kw.setdefault("env", dict(os.environ, LC_ALL="C"))
    p = subprocess.run([str(x) for x in argv], capture_output=True, timeout=30, **kw)
    if p.returncode:
        raise AssertionError((argv, p.returncode, p.stdout[-2000:], p.stderr[-2000:]))
    return p.stdout


def extract(obj, raw):
    before = obj.read_bytes()
    discard = raw.with_suffix(".discard.o")
    run(["objcopy", "--dump-section", ".text=" + str(raw), obj, discard])
    discard.unlink()
    assert obj.read_bytes() == before
    return raw.read_bytes()


def symbol(obj, name):
    rows = [int(f[0], 16) for line in run(["nm", "-n", obj]).decode().splitlines()
            if len(f := line.split()) >= 3 and f[-1] == name]
    assert len(rows) == 1, (obj, name, rows)
    return rows[0]


def link(out, name, obj, expected, macro):
    case = out / name
    case.mkdir()
    observer, guest, image = (case / x for x in ("observer.o", "guest.elf", "guest32.elf"))
    flags = ["-D" + macro] if macro else []
    run(["cc", "-m64", "-c", "-nostdlib", "-fno-pie", *flags, BOOT, "-o", observer])
    run(["ld", "-nostdlib", "-z", "noexecstack", "-z", "max-page-size=0x1000",
         "-T", LINKER, "-o", guest, observer, obj])
    run(["objcopy", "-O", "elf32-i386", guest, image])
    rows = [line.split() for line in run(["objdump", "-h", guest]).decode().splitlines()
            if len(line.split()) >= 6 and line.split()[1] == ".text"]
    assert len(rows) == 1
    offset = symbol(guest, "f0") - int(rows[0][3], 16) - symbol(obj, "f0")
    assert offset >= 0
    text64 = extract(guest, case / "guest64.text")
    text32 = extract(image, case / "guest32.text")
    assert text64 == text32 and text64[offset:offset+len(expected)] == expected
    return image, {"guest64_sha256": digest(guest.read_bytes()),
                   "guest32_sha256": digest(image.read_bytes()),
                   "subject_text_offset": offset, "subject_text_sha256": digest(expected)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compiler-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    candidate = args.compiler_dir.resolve()
    report = json.loads((candidate / "report.json").read_bytes())
    compiler = candidate / "compiler-rebuilt-2"
    assert report["status"] == "PASS" and report["native_generations"] == 3 and report["empty_path_rebuilds"] == 2
    assert report["compiler_sha256"] == COMPILER_SHA == digest(compiler.read_bytes())
    assert report["source_sha256"] == COMPILER_SOURCE_SHA == digest((candidate / "candidate.hepta").read_bytes())
    source = SOURCE.read_bytes()
    native = run([compiler], input=source, env={"PATH": ""})
    assert native.startswith(b"\x7fELF") and native == run([compiler], input=source, env={"PATH": ""})
    obj = out / "native.o"
    obj.write_bytes(native)
    assert not run(["nm", "-u", obj]).strip()
    relocs = run(["readelf", "-Wr", obj])
    (out / "relocations.txt").write_bytes(relocs)
    assert b"There are no relocations" in relocs and b"R_X86_64_" not in relocs
    text = extract(obj, out / "native.text")
    # Independent GNU assembler is an oracle for actual operation sequences.
    oracle = out / "oracle.S"
    oracle.write_text(".text\n movq %cr4,%rax\n rdmsr\n shlq $32,%rdx\n orq %rdx,%rax\n movq %rax,%rdx\n shrq $32,%rdx\n wrmsr\n")
    run(["as", "--64", "-o", out / "oracle.o", oracle])
    ops = extract(out / "oracle.o", out / "oracle.text")
    assert ops == bytes.fromhex("0f20e00f3248c1e2204809d04889c248c1ea200f30")
    cr4, read, write = ops[:3], ops[3:12], ops[12:]
    assert text.count(cr4) == 1 and text.count(read) == 8 and text.count(write) == 4
    assert text.index(cr4) < text.index(read) < text.index(write) < text.rindex(read)
    # Preserve all validation and final readback; remove only the actual
    # WRMSR instruction. The real HIA function must return readback error.
    mutants = []
    offset = 0
    for stage in range(4):
        pos = text.index(write, offset)
        offset = pos + len(write)
        mutated = text[:pos] + write[:-2] + b"\x90\x90" + text[offset:]
        badraw = out / f"no-write-{stage}.text"
        badraw.write_bytes(mutated)
        badobj = out / f"no-write-{stage}.o"
        run(["objcopy", "--update-section", ".text=" + str(badraw), obj, badobj])
        assert extract(badobj, out / f"no-write-{stage}-readback.text") == mutated
        assert symbol(obj, "f0") == symbol(badobj, "f0")
        mutants.append((f"write-nop-{stage}", badobj, mutated, f"HIA_TEST_NOP_STAGE={stage}", 35, b"N"))
    receipt = {"status": "FAIL", "compiler_sha256": COMPILER_SHA,
               "compiler_source_sha256": COMPILER_SOURCE_SHA,
               "subject_source_sha256": digest(source), "subject_object_sha256": digest(native),
               "subject_text_sha256": digest(text), "observer_sha256": digest(BOOT.read_bytes()),
               "linker_sha256": digest(LINKER.read_bytes()), "cases": [],
               "full_linux_acceptance": "HOLD", "production_toolchain_changed": False,
               "authority_proved": False, "native_syscall_entry_proved": False,
               "native_ordered_syscall_msr_init": True, "native_syscall_return_proved": False}
    try:
        for name, subject, code, macro, rc, serial in (
            ("real-cpl3-syscall", obj, text, None, 33, b"P"),
            ("stale-lstar", obj, text, "HIA_TEST_STALE", 35, b"S"),
            ("stale-efer", obj, text, "HIA_TEST_STALE_EFER", 35, b"S"),
            ("stale-star", obj, text, "HIA_TEST_STALE_STAR", 35, b"S"),
            ("stale-fmask", obj, text, "HIA_TEST_STALE_FMASK", 35, b"S"),
            ("noncanonical", obj, text, "HIA_TEST_NONCANONICAL", 35, b"B"),
            ("unaligned", obj, text, "HIA_TEST_UNALIGNED", 35, b"B"),
            ("already-active", obj, text, "HIA_TEST_ACTIVE", 35, b"E"),
            *mutants):
            image, binding = link(out, name, subject, code, macro)
            for machine in ("pc", "q35"):
                row = {"case": name, "machine": machine, **binding, "expected_rc": rc,
                       "expected_serial": serial.decode(), "status": "FAIL"}
                receipt["cases"].append(row)
                argv = ["qemu-system-x86_64", "-machine", machine, "-cpu", "qemu64", "-m", "64M",
                        "-accel", "tcg", "-display", "none", "-serial", "none", "-monitor", "none",
                        "-no-reboot", "-no-shutdown", "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
                        "-debugcon", "stdio", "-global", "isa-debugcon.iobase=0xe9", "-kernel", str(image)]
                try:
                    p = subprocess.run(argv, capture_output=True, timeout=20)
                    row.update(returncode=p.returncode, serial=p.stdout.decode(errors="replace"),
                               stderr=p.stderr.decode(errors="replace")[-3000:])
                    assert (p.returncode, p.stdout) == (rc, serial), row
                    row["status"] = "PASS"
                except subprocess.TimeoutExpired:
                    row["status"] = "TIMEOUT"
                    raise
        assert SOURCE.read_bytes() == source and obj.read_bytes() == native and digest(compiler.read_bytes()) == COMPILER_SHA
        receipt["status"] = "PASS"
    finally:
        (out / "report.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()

