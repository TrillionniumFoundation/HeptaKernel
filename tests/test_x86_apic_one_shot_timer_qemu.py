#!/usr/bin/env python3
"""Independent xAPIC one-shot timer and EOI hardware oracle for native HIA."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/x86_apic_one_shot_timer.hepta"
BOOT = ROOT / "tests/fixtures/x86_apic_one_shot_timer.S"
LINKER = ROOT / "tests/fixtures/x86_apic_one_shot_timer.ld"
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
    # The actual aligned MMIO write instruction is independently assembled.
    oracle = out / "oracle.S"
    oracle.write_text(".text\n testb $3,%dl\n jz 1f\n ud2\n1:\n movq -256(%rbp),%rax\n movl %eax,(%rdx)\n")
    run(["as", "--64", "-o", out / "oracle.o", oracle])
    write = extract(out / "oracle.o", out / "oracle.text")
    assert write == bytes.fromhex("f6c20374020f0b488b8500ffffff8902")
    # Only the compiler's stack-slot displacement may differ from GNU as.
    indices = [i+14 for i in range(len(text)-15)
               if text[i:i+10] == write[:10] and text[i+14:i+16] == write[14:16]]
    assert len(indices) == 4 and text.count(write[-2:]) == 4
    def body_start(name, limit):
        stub = symbol(obj, name)
        code = text[stub:limit]
        calls = [i for i in range(len(code)-7)
                 if code[i] == 0xe8 and code[i+5:i+8] == bytes.fromhex("488b85")]
        assert len(calls) == 1, (name, code.hex())
        i = calls[0]
        return stub+i+5+int.from_bytes(code[i+1:i+5], "little", signed=True)
    f0, f1 = symbol(obj, "f0"), symbol(obj, "f1")
    assert 0 <= body_start("f0",f1) <= indices[0] < indices[1] < indices[2] < body_start("f1",len(text)) <= indices[3] < f0 < f1
    mutants = []
    for name, pos, macro, serial in (
        ("divide-nop", indices[0], "HIA_TEST_DIV_NOP", b"V"),
        ("lvt-nop", indices[1], "HIA_TEST_LVT_NOP", b"L"),
        ("count-nop", indices[2], "HIA_TEST_COUNT_NOP", b"N"),
        ("eoi-nop", indices[3], "HIA_TEST_EOI_NOP", b"M")):
        mutated = text[:pos] + b"\x90\x90" + text[pos+2:]
        badraw = out / (name + ".text")
        badraw.write_bytes(mutated)
        badobj = out / (name + ".o")
        run(["objcopy", "--update-section", ".text=" + str(badraw), obj, badobj])
        assert extract(badobj, out / (name + "-readback.text")) == mutated
        assert symbol(obj, "f0") == symbol(badobj, "f0") and symbol(obj, "f1") == symbol(badobj, "f1")
        mutants.append((name, badobj, mutated, macro, 35, serial))
    receipt = {"status":"FAIL", "compiler_sha256":COMPILER_SHA,
        "compiler_source_sha256":COMPILER_SOURCE_SHA,
        "subject_source_sha256":digest(source), "subject_object_sha256":digest(native),
        "subject_text_sha256":digest(text), "observer_sha256":digest(BOOT.read_bytes()),
        "linker_sha256":digest(LINKER.read_bytes()), "cases":[],
        "full_linux_acceptance":"HOLD", "production_toolchain_changed":False,
        "apic_authority_proved":False, "scheduler_clock_proved":False, "timer_teardown_native_hia":False, "periodic_timer_proved":False,
        "native_interrupt_entry_proved":False, "native_iretq_proved":False}
    try:
        for name, subject, code, macro, rc, serial in (
            ("native-one-shot-and-eoi",obj,text,None,33,b"P"),
            ("bad-base",obj,text,"HIA_TEST_BAD_BASE",35,b"B"),
            ("stale-msr",obj,text,"HIA_TEST_STALE",35,b"S"),
            ("stale-lvt",obj,text,"HIA_TEST_STALE_LVT",35,b"O"),
            ("stale-divide",obj,text,"HIA_TEST_STALE_DIV",35,b"O"),
            ("software-disabled",obj,text,"HIA_TEST_DISABLED",35,b"D"),
            ("priority-blocked",obj,text,"HIA_TEST_PRIORITY",35,b"D"),
            ("active-masked-timer",obj,text,"HIA_TEST_ACTIVE",35,b"R"),
            ("periodic-mode-refused",obj,text,"HIA_TEST_PERIODIC",35,b"R"),
            *mutants):
            image, binding = link(out, name, subject, code, macro)
            for machine in ("pc","q35"):
                row = {"case":name,"machine":machine,**binding,"expected_rc":rc,
                       "expected_serial":serial.decode(),"status":"FAIL"}
                receipt["cases"].append(row)
                argv = ["qemu-system-x86_64","-machine",machine,"-cpu","qemu64",
                        "-smp","1","-m","64M","-accel","tcg","-display","none",
                        "-serial","none","-monitor","none","-no-reboot","-no-shutdown",
                        "-device","isa-debug-exit,iobase=0xf4,iosize=0x04",
                        "-debugcon","stdio","-global","isa-debugcon.iobase=0xe9","-kernel",str(image)]
                try:
                    p = subprocess.run(argv,capture_output=True,timeout=20)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors="replace"),
                               stderr=p.stderr.decode(errors="replace")[-3000:])
                    assert (p.returncode,p.stdout) == (rc,serial), row
                    row["status"]="PASS"
                except subprocess.TimeoutExpired:
                    row["status"]="TIMEOUT"
                    raise
        assert SOURCE.read_bytes() == source and obj.read_bytes() == native and digest(compiler.read_bytes()) == COMPILER_SHA
        receipt.update(status="PASS", native_xapic_one_shot_timer=True, native_xapic_eoi=True)
    finally:
        (out / "report.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        print(json.dumps(receipt,sort_keys=True))

if __name__ == "__main__":
    main()
