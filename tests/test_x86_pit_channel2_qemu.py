#!/usr/bin/env python3
"""Independent PIT channel-2 hardware and native byte-custody oracle."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
import re
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/x86_pit_channel2.hepta"
BOOT = ROOT / "tests/fixtures/x86_pit_channel2.S"
LINKER = ROOT / "tests/fixtures/x86_pit_channel2.ld"
COMPILER_SHA = "753b55eda6fca1e74ad8bd81d6e4902f0ed673b3c2a58b0339af4f38d7581f58"
COMPILER_SOURCE_SHA = "240df3ba764066c4fb17cb8003f572dc6744e01c7891cbe7e4b940329b5a7fc1"

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


def instruction_rows(asm):
    # Parse raw instruction rows without requiring symbol annotations,
    # a particular call mnemonic, hexadecimal prefix or tab spacing.
    for line in asm.splitlines():
        m = re.match(r"^\s*(?:0x)?([0-9a-fA-F]+):\s+(.*?)\s*$", line)
        if not m:
            continue
        fields = m[2].split()
        n = 0
        while n < len(fields) and re.fullmatch(r"[0-9a-fA-F]{2}", fields[n]):
            n += 1
        if n and n < len(fields):
            yield int(m[1], 16), bytes.fromhex(" ".join(fields[:n])), fields[n], fields[n+1:]


def decoded_rows(obj):
    return list(instruction_rows(run(["objdump", "-d", "--show-raw-insn",
                                      "--insn-width=16", obj]).decode()))


def implementation_ranges(obj, text):
    names = ("f0", "f1", "f2", "f3")
    wrappers = {name: symbol(obj, name) for name in names}
    rows = decoded_rows(obj)
    entries = {}
    for name, lo in wrappers.items():
        hi = min((x for x in wrappers.values() if x > lo), default=len(text))
        region = [r for r in rows if lo <= r[0] < hi]
        matches = [(at, raw, operands) for at, raw, mnemonic, operands in region
                   if mnemonic in ("call", "callq")]
        assert len(matches) == 1, (name, matches, region)
        at, raw, operands = matches[0]
        assert len(raw) == 5 and raw[0] == 0xe8 and text[at:at+5] == raw and at+5 <= hi
        assert operands and re.fullmatch(r"(?:0x)?[0-9a-fA-F]+", operands[0]), (name, operands)
        target = at + 5 + int.from_bytes(raw[1:], "little", signed=True)
        assert target == int(operands[0], 16)
        entries[name] = target
    end = min(wrappers.values())
    starts = sorted(entries.values())
    assert len(set(starts)) == len(names) and starts[0] == 0 and starts[-1] < end
    assert all(any(at == start for at, _, _, _ in rows) for start in starts)
    return {name: (start, next(x for x in starts + [end] if x > start))
            for name, start in entries.items()}


def check_opcode_owner(obj, text, ranges, owner, opcode, mnemonic):
    lo, hi = ranges[owner]
    assert text[lo:hi].count(opcode) == 1
    pos = text.index(opcode, lo, hi)
    assert lo <= pos and pos + len(opcode) <= hi, (owner, pos, lo, hi)
    matches = [(raw, op, args) for at, raw, op, args in decoded_rows(obj) if at == pos]
    assert len(matches) == 1, (owner, pos, matches)
    raw, op, args = matches[0]
    assert raw == opcode and re.match(mnemonic + r"(?:q)?\b", " ".join([op] + args)), (owner, pos, matches)
    return pos


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
    ranges = implementation_ranges(obj, text)

    # The independent assembler supplies the exact I/O instruction encodings,
    # not the HIA subject. Identify instructions by their decoded boundaries,
    # not by a search for a byte that may also appear in an immediate.
    asm = out / "oracle.S"
    asm.write_text(".text\n outb %al,(%dx)\n inb (%dx),%al\n movzbl %al,%eax\n")
    run(["as", "--64", "-o", out / "oracle.o", asm])
    opcode = extract(out / "oracle.o", out / "oracle.text")
    assert opcode == bytes.fromhex("eeec0fb6c0")
    rows = decoded_rows(obj)
    def positions(owner, raw, name):
        lo, hi = ranges[owner]
        found = [at for at, data, op, args in rows if lo <= at < hi
                 and data == raw and op in (name, name+"b")]
        assert all(text[at:at+len(raw)] == raw for at in found)
        return found
    stores = {name: positions(name, opcode[:1], "out") for name in ranges}
    loads = {name: positions(name, opcode[1:2], "in") for name in ranges}
    assert [len(stores[f"f{i}"]) for i in range(4)] == [4,1,0,1], stores
    assert [len(loads[f"f{i}"]) for i in range(4)] == [4,2,1,2], loads
    mutations = (
        ("deleted-count-high-byte", stores["f0"][2], opcode[:1], b"\x90", "HIA_TEST_PIT_LOAD_NOP", b"L"),
        ("deleted-gate-start", stores["f1"][0], opcode[:1], b"\x90", "HIA_TEST_PIT_START_NOP", b"S"),
        ("deleted-status-read", loads["f2"][0], opcode[1:], b"\x31\xc0\x90\x90", "HIA_TEST_PIT_WAIT_NOP", b"W"),
        ("deleted-gate-stop", stores["f3"][0], opcode[:1], b"\x90", "HIA_TEST_PIT_STOP_NOP", b"T"),
    )
    cases = [("two-native-reference-windows", obj, text, None, 33, b"P")]
    for name, pos, expected, replacement, macro, serial in mutations:
        assert len(expected) == len(replacement) and text[pos:pos+len(expected)] == expected
        changed = text[:pos] + replacement + text[pos+len(expected):]
        raw = out / (name + ".text")
        raw.write_bytes(changed)
        mutated = out / (name + ".o")
        run(["objcopy", "--update-section", ".text=" + str(raw), obj, mutated])
        assert extract(mutated, out / (name + "-readback.text")) == changed
        assert implementation_ranges(mutated, changed) == ranges
        assert all(symbol(mutated, name) == symbol(obj, name) for name in ranges)
        cases.append((name, mutated, changed, macro, 35, serial))
    receipt = {"status": "FAIL", "compiler_sha256": COMPILER_SHA, "compiler_source_sha256": COMPILER_SOURCE_SHA,
               "subject_source_sha256": digest(source), "subject_object_sha256": digest(native),
               "subject_text_sha256": digest(text), "observer_sha256": digest(BOOT.read_bytes()),
               "linker_sha256": digest(LINKER.read_bytes()), "implementation_ranges": ranges,
               "port_in_offsets": loads, "port_out_offsets": stores, "cases": [],
               "full_linux_acceptance": "HOLD", "production_toolchain_changed": False,
               "pit_resource_authority_proved": False, "general_clocksource_proved": False}
    try:
        for name, subject, code, macro, rc, serial in cases:
            image, binding = link(out, name, subject, code, macro)
            for machine in ("pc", "q35"):
                row = {"case": name, "machine": machine, **binding, "expected_rc": rc, "status": "FAIL"}
                receipt["cases"].append(row)
                argv = ["qemu-system-x86_64", "-machine", machine, "-cpu", "qemu64",
                        "-m", "64M", "-accel", "tcg", "-display", "none", "-serial", "none",
                        "-monitor", "none", "-no-reboot", "-no-shutdown",
                        "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
                        "-debugcon", "stdio", "-global", "isa-debugcon.iobase=0xe9", "-kernel", str(image)]
                try:
                    p = subprocess.run(argv, capture_output=True, timeout=20)
                    row.update(returncode=p.returncode, serial=p.stdout.decode(errors="replace"),
                               stderr=p.stderr.decode(errors="replace")[-3000:])
                    assert p.returncode == rc, row
                    if name == "two-native-reference-windows":
                        m = re.fullmatch(rb"([0-9a-f]{8}):([0-9a-f]{8}):P", p.stdout)
                        assert m, row
                        short, long = (int(x,16) for x in m.groups())
                        assert short > 0 and 3*short <= 2*long <= 5*short, row
                        row.update(short_apic_ticks=short,long_apic_ticks=long,reference_ticks=[12000,24000])
                    else:
                        assert p.stdout == serial, row
                    row["status"] = "PASS"
                except subprocess.TimeoutExpired:
                    row["status"] = "TIMEOUT"
                    raise
        assert SOURCE.read_bytes() == source and obj.read_bytes() == native
        assert digest(compiler.read_bytes()) == COMPILER_SHA
        assert digest((candidate / "candidate.hepta").read_bytes()) == COMPILER_SOURCE_SHA
        receipt.update(status="PASS", native_pit_load_start_wait_stop=True,
                       independent_pit_latch_readback=True, independent_apic_elapsed_ratio=True,
                       native_poll_budget_exhaustion=True, native_bounded_latch_readback=True, arbitrary_pit_configuration_restored=False)
    finally:
        (out / "report.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        print(json.dumps(receipt,sort_keys=True))

if __name__ == "__main__":
    main()
