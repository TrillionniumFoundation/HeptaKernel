#!/usr/bin/env python3
"""Independent two-vCPU remote TLB invalidation and post-IRET ACK oracle."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
import re
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/x86_remote_tlb_shootdown.hepta"
BOOT = ROOT / "tests/fixtures/x86_remote_tlb_shootdown.S"
LINKER = ROOT / "tests/fixtures/x86_apic_self_ipi.ld"
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
    names = ("f0", "f1", "f2", "f3", "f4", "f5")
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


def check_disassembly_display_variants():
    for line in (
        " 1846: e8 b5 e7 ff ff call 0 <f0-0x1801>",
        " 0x1846: e8 b5 e7 ff ff callq 0x0",
        " 1846:\te8 b5 e7 ff ff\tcall 0x0000000000000000 <.text>",
    ):
        rows = list(instruction_rows(line))
        assert len(rows) == 1
        at, raw, op, operands = rows[0]
        assert at == 0x1846 and raw == bytes.fromhex("e8b5e7ffff")
        assert op in ("call", "callq") and int(operands[0], 16) == 0
        assert at + len(raw) + int.from_bytes(raw[1:], "little", signed=True) == 0


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
    oracle = out / "oracle.S"
    oracle.write_text(".text\n invlpg (%rax)\n")
    run(["as", "--64", "-o", out / "oracle.o", oracle])
    opcode = extract(out / "oracle.o", out / "oracle.text")
    assert opcode == bytes.fromhex("0f0138") and text.count(opcode) == 1
    check_disassembly_display_variants()
    ranges = implementation_ranges(obj, text)
    pos = check_opcode_owner(obj, text, ranges, "f2", opcode, "invlpg")
    mutated = text[:pos] + b"\x90"*3 + text[pos+3:]
    badraw = out / "flush-nop.text"
    badraw.write_bytes(mutated)
    badobj = out / "flush-nop.o"
    run(["objcopy", "--update-section", ".text=" + str(badraw), obj, badobj])
    assert extract(badobj, out / "flush-nop-readback.text") == mutated
    assert all(symbol(obj, f) == symbol(badobj, f) for f in ("f0", "f1", "f2", "f3", "f4", "f5"))
    # Independently assemble the CAS opcode and attribute each occurrence to its owner.
    cas_oracle = out / "cas-oracle.S"
    cas_oracle.write_text(".text\n lock cmpxchgq %rcx,(%rdx)\n")
    run(["as", "--64", "-o", out / "cas-oracle.o", cas_oracle])
    cas = extract(out / "cas-oracle.o", out / "cas-oracle.text")
    assert cas == bytes.fromhex("f0480fb10a") and text.count(cas) == 3
    cas_pos = check_opcode_owner(obj, text, ranges, "f3", cas, "lock\\s+cmpxchg")
    pte_text = text[:cas_pos] + b"\x90" * len(cas) + text[cas_pos+len(cas):]
    pte_raw = out / "pte-cas-nop.text"
    pte_raw.write_bytes(pte_text)
    pte_obj = out / "pte-cas-nop.o"
    run(["objcopy", "--update-section", ".text=" + str(pte_raw), obj, pte_obj])
    assert extract(pte_obj, out / "pte-cas-nop-readback.text") == pte_text
    assert all(symbol(obj, f) == symbol(pte_obj, f) for f in ("f0", "f1", "f2", "f3", "f4", "f5"))
    assert implementation_ranges(badobj, mutated) == implementation_ranges(pte_obj, pte_text) == ranges
    ack_pos = check_opcode_owner(obj, text, ranges, "f4", cas, "lock\\s+cmpxchg")
    assert ack_pos != cas_pos
    ack_text = text[:ack_pos] + b"\x90" * len(cas) + text[ack_pos+len(cas):]
    ack_raw = out / "ack-cas-nop.text"
    ack_raw.write_bytes(ack_text)
    ack_obj = out / "ack-cas-nop.o"
    run(["objcopy", "--update-section", ".text=" + str(ack_raw), obj, ack_obj])
    assert extract(ack_obj, out / "ack-cas-nop-readback.text") == ack_text
    assert all(symbol(obj, f) == symbol(ack_obj, f) for f in ("f0", "f1", "f2", "f3", "f4", "f5"))
    assert implementation_ranges(ack_obj, ack_text) == ranges
    assert ack_text[cas_pos:cas_pos+len(cas)] == cas
    assert pte_text[ack_pos:ack_pos+len(cas)] == cas
    consume_pos = check_opcode_owner(obj, text, ranges, "f5", cas, "lock\\s+cmpxchg")
    assert len({cas_pos, ack_pos, consume_pos}) == 3
    consume_text = text[:consume_pos] + b"\x90" * len(cas) + text[consume_pos+len(cas):]
    consume_raw = out / "consume-cas-nop.text"
    consume_raw.write_bytes(consume_text)
    consume_obj = out / "consume-cas-nop.o"
    run(["objcopy", "--update-section", ".text=" + str(consume_raw), obj, consume_obj])
    assert extract(consume_obj, out / "consume-cas-nop-readback.text") == consume_text
    assert all(symbol(obj, f) == symbol(consume_obj, f) for f in ("f0", "f1", "f2", "f3", "f4", "f5"))
    assert implementation_ranges(consume_obj, consume_text) == ranges
    assert consume_text[cas_pos:cas_pos+len(cas)] == cas
    assert consume_text[ack_pos:ack_pos+len(cas)] == cas
    assert pte_text[consume_pos:consume_pos+len(cas)] == cas
    assert ack_text[consume_pos:consume_pos+len(cas)] == cas
    assert mutated[consume_pos:consume_pos+len(cas)] == cas
    receipt = {"status":"FAIL", "compiler_sha256":COMPILER_SHA,
        "compiler_source_sha256":COMPILER_SOURCE_SHA,
        "subject_source_sha256":digest(source), "subject_object_sha256":digest(native),
        "subject_text_sha256":digest(text), "implementation_ranges":ranges,
        "invlpg_offset":pos, "pte_cas_offset":cas_pos, "ack_cas_offset":ack_pos, "consume_cas_offset":consume_pos, "observer_sha256":digest(BOOT.read_bytes()),
        "linker_sha256":digest(LINKER.read_bytes()), "cases":[],
        "full_linux_acceptance":"HOLD", "production_toolchain_changed":False,
        "apic_authority_proved":False, "cross_cpu_ipi_proved":False,
        "remote_tlb_shootdown_proved":False, "native_ap_bootstrap_proved":False,
        "native_interrupt_entry_proved":False, "native_iretq_proved":False}
    try:
        for name, subject, code, macro, rc, serial in (
            ("native-remote-shootdown",obj,text,None,33,b"P"),
            ("invlpg-nop",badobj,mutated,"HIA_TEST_FLUSH_NOP",35,b"FR"),
            ("missing-ack",obj,text,"HIA_TEST_ACK_MISSING",35,b"K"),
            ("pte-cas-nop",pte_obj,pte_text,"HIA_TEST_PTE_CAS_NOP",35,b"J"),
            ("ack-cas-nop",ack_obj,ack_text,"HIA_TEST_ACK_CAS_NOP",35,b"L"),
            ("pending-consume-cas-nop",consume_obj,consume_text,"HIA_TEST_CONSUME_PENDING_NOP",35,b"U"),
            ("completed-consume-cas-nop",consume_obj,consume_text,"HIA_TEST_CONSUME_CAS_NOP",35,b"V")):
            image, binding = link(out, name, subject, code, macro)
            for machine in ("pc","q35"):
                row = {"case":name,"machine":machine,**binding,"expected_rc":rc,
                       "expected_serial":serial.decode(),"status":"FAIL"}
                receipt["cases"].append(row)
                argv = ["qemu-system-x86_64","-machine",machine,"-cpu","qemu64",
                        "-smp","2,sockets=1,cores=2,threads=1","-m","64M","-accel","tcg","-display","none",
                        "-serial","none","-monitor","none","-no-reboot","-no-shutdown",
                        "-device","isa-debug-exit,iobase=0xf4,iosize=0x04",
                        "-debugcon","stdio","-global","isa-debugcon.iobase=0xe9","-kernel",str(image)]
                try:
                    p = subprocess.run(argv,capture_output=True,timeout=20)
                    row.update(returncode=p.returncode,serial=p.stdout.decode(errors="replace"),
                               stderr=p.stderr.decode(errors="replace")[-3000:])
                    if name == "invlpg-nop":
                        assert p.returncode == rc and p.stdout in (b"F", b"R"), row
                        row["immediate_stale_observed"] = True
                        row["post_iret_stale_observed"] = p.stdout == b"F"
                        row["ack_withheld"] = True
                    else:
                        assert (p.returncode,p.stdout) == (rc,serial), row
                    row["status"]="PASS"
                except subprocess.TimeoutExpired:
                    row["status"]="TIMEOUT"
                    raise
        assert SOURCE.read_bytes() == source and obj.read_bytes() == native and digest(compiler.read_bytes()) == COMPILER_SHA
        receipt.update(status="PASS", native_xapic_remote_ipi=True, native_xapic_eoi=True,
                       cross_cpu_ipi_proved=True, exact_fixture_vcpus=2,
                       remote_tlb_shootdown_proved=True, native_ap_bootstrap_proved=False,
                       original_post_iret_stale_control_met=all(
                           r["post_iret_stale_observed"] for r in receipt["cases"]
                           if r["case"] == "invlpg-nop"),
                       native_mapping_publication=True, native_ack_publication=True,
                       ack_cas_deleted_detected=True, ack_wrong_cpu_rejected=True,
                       ack_stale_future_duplicate_rejected=True, ack_observation_failure_rejected=True,
                       ack_generation_fixture=2, ack_pending_word=4, ack_completed_word=5,
                       ack_resource_authority_proved=False,
                       pte_cas_deleted_detected=True, publication_authority_proved=False,
                       native_ack_consumption=True, pending_ack_consume_rejected=True,
                       stale_future_duplicate_consume_rejected=True, wrong_cpu_consume_rejected=True,
                       consume_cas_deleted_detected=True, consumed_word=0,
                       repeated_generation_lifecycle_proved=False, page_reclamation_proved=False,
                       fixed_page_only=True, arbitrary_cohort_proved=False)
    finally:
        (out / "report.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        print(json.dumps(receipt,sort_keys=True))

if __name__ == "__main__":
    main()
