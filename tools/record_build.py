#!/usr/bin/env python3
"""Bind tested products to native HIA bytes and declared build inputs.

This is a host-side artifact check, not an assembler or kernel implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Elf:
    def __init__(self, path):
        self.raw = Path(path).read_bytes()
        raw = self.raw
        if raw[:4] != b"\x7fELF" or raw[5] != 1 or raw[4] not in (1, 2):
            raise ValueError("expected a little-endian ELF artifact")
        self.bits = 64 if raw[4] == 2 else 32
        if self.bits == 64:
            self.entry, phoff, shoff = struct.unpack_from("<3Q", raw, 24)
            phsize, phnum, shsize, shnum, shstr = struct.unpack_from("<5H", raw, 54)
            shfmt = "<IIQQQQIIQQ"
        else:
            self.entry, phoff, shoff = struct.unpack_from("<3I", raw, 24)
            phsize, phnum, shsize, shnum, shstr = struct.unpack_from("<5H", raw, 42)
            shfmt = "<10I"
        self.headers = [struct.unpack_from(shfmt, raw, shoff + i * shsize) for i in range(shnum)]
        h = self.headers[shstr]
        names = raw[h[4]:h[4] + h[5]]
        self.sections = {}
        for h in self.headers:
            name = names[h[0]:].split(b"\0", 1)[0].decode("ascii")
            self.sections[name] = h
        for i in range(phnum):
            if struct.unpack_from("<I", raw, phoff + i * phsize)[0] == 3:
                raise ValueError("kernel artifact unexpectedly requires PT_INTERP")

    def section_bytes(self, name):
        h = self.sections[name]
        return self.raw[h[4]:h[4] + h[5]]

    def symbol(self, name):
        table = self.sections[".symtab"]
        strings_h = self.headers[table[6]]
        strings = self.raw[strings_h[4]:strings_h[4] + strings_h[5]]
        for at in range(table[4], table[4] + table[5], table[9]):
            if self.bits == 64:
                spelling, info, other, section, value, size = struct.unpack_from("<IBBHQQ", self.raw, at)
            else:
                spelling, value, size, info, other, section = struct.unpack_from("<IIIBBH", self.raw, at)
            found = strings[spelling:].split(b"\0", 1)[0].decode("ascii")
            if found == name:
                return value
        raise ValueError("missing symbol " + name)

    def text_at(self, address, size):
        section = self.sections[".text"]
        offset = address - section[3]
        if offset < 0 or size > section[5] - offset:
            raise ValueError("symbol extent is outside .text")
        return self.section_bytes(".text")[offset:offset + size]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", required=True)
    ap.add_argument("--report", type=Path, default=Path("build/build-report.json"))
    args = ap.parse_args()
    report = {"schema": "heptakernel.build-evidence.v1", "whole_kernel_rewrite_complete": False}
    try:
        compiler = shutil.which(args.compiler)
        if compiler is None:
            raise ValueError("native compiler is unavailable")
        compiler = str(Path(compiler).resolve())
        lock = json.loads(Path("compatibility/hia-toolchain-lock.json").read_text())
        compiler_hash = sha(Path(compiler).read_bytes())
        if compiler_hash != lock["compiler_sha256"]:
            raise ValueError("native compiler does not match the lock")
        source = Path("src/kernel.hepta").read_bytes()
        obj = Path("build/kernel.o").read_bytes()
        repeated = subprocess.run([compiler], input=source, capture_output=True,
                                  timeout=20, env={"PATH": ""})
        if repeated.returncode or repeated.stderr or repeated.stdout != obj:
            raise ValueError("exact HIA source did not reproduce the tested object")
        undefined = subprocess.check_output(["nm", "-u", "build/kernel.o"], text=True).strip()
        if undefined:
            raise ValueError("HIA object contains external dependencies: " + undefined)
        arena_source = Path("src/arena_router.hepta").read_bytes()
        arena_object = Path("build/arena-router.o").read_bytes()
        rebuilt_arena = subprocess.run([compiler], input=arena_source, capture_output=True,
                                       timeout=20, env={"PATH": ""})
        if rebuilt_arena.returncode or rebuilt_arena.stderr or rebuilt_arena.stdout != arena_object:
            raise ValueError("native HIA multi-arena router bytes not reproducible")
        if subprocess.check_output(["nm", "-u", "build/arena-router.o"], text=True).strip():
            raise ValueError("HIA multi-arena router has undefined symbols")
        if Elf("build/arena-router.so").section_bytes(".text") != Elf("build/arena-router.o").section_bytes(".text"):
            raise ValueError("native HIA multi-arena router loaded image differs from source object")
        arena_code = Elf("build/arena-router.o").section_bytes(".text")
        if Elf("build/arena-boot.o").section_bytes(".text") != arena_code:
            raise ValueError("native HIA arena router symbol rename changed code")
        e820_source = Path("src/e820_region.hepta").read_bytes()
        e820_object = Path("build/e820-region.o").read_bytes()
        rebuilt_e820 = subprocess.run([compiler], input=e820_source, capture_output=True,
                                      timeout=20, env={"PATH": ""})
        if rebuilt_e820.returncode or rebuilt_e820.stderr or rebuilt_e820.stdout != e820_object:
            raise ValueError("native HIA E820 bytes not reproducible")
        if subprocess.check_output(["nm", "-u", "build/e820-region.o"], text=True).strip():
            raise ValueError("E820 native object has undefined symbols")
        e820_original = Elf("build/e820-region.o")
        e820_code = e820_original.section_bytes(".text")
        if Elf("build/e820-boot.o").section_bytes(".text") != e820_code:
            raise ValueError("symbol-only E820 rename changed code")
        object_elf, image64, image32 = [Elf(p) for p in
                                      ("build/kernel.o", "build/kernel.elf", "build/kernel-multiboot.elf")]
        code = object_elf.section_bytes(".text")
        entry = image64.symbol("f0")
        if image32.symbol("f0") != entry or image32.entry != image64.entry:
            raise ValueError("Multiboot container changed entry symbols")
        if image64.text_at(entry, len(code)) != code or image32.text_at(entry, len(code)) != code:
            raise ValueError("linked boot images do not contain the exact HIA code at f0")
        arena_entry = image64.symbol("arena_f0")
        if image32.symbol("arena_f0") != arena_entry:
            raise ValueError("native HIA arena entry mismatch in packed boot image")
        if (image64.text_at(arena_entry, len(arena_code)) != arena_code or
                image32.text_at(arena_entry, len(arena_code)) != arena_code):
            raise ValueError("default QEMU boot images lack exact native HIA arena machine code")
        e820_entry = image64.symbol("e820_f0")
        if image32.symbol("e820_f0") != e820_entry:
            raise ValueError("E820 Multiboot entry mismatch")
        if (image64.text_at(e820_entry, len(e820_code)) != e820_code or
                image32.text_at(e820_entry, len(e820_code)) != e820_code):
            raise ValueError("native HIA E820 code not preserved in boot images")
        # Test-only reserved-memory images must carry byte-exact HIA.
        liar_source = Path("tests/negative/e820_allow_all.hepta").read_bytes()
        liar_object = Path("build/e820-allow-all.o").read_bytes()
        rebuilt_liar = subprocess.run([compiler], input=liar_source, capture_output=True,
                                      timeout=20, env={"PATH": ""})
        if rebuilt_liar.returncode or rebuilt_liar.stderr or rebuilt_liar.stdout != liar_object:
            raise ValueError("dishonest HIA E820 control not reproducible")
        liar_code = Elf("build/e820-allow-all.o").section_bytes(".text")
        if Elf("build/e820-unsafe-boot.o").section_bytes(".text") != liar_code:
            raise ValueError("dishonest E820 symbol rename changed code")
        if Elf("build/arena-unsafe-boot.o").section_bytes(".text") != liar_code:
            raise ValueError("dishonest HIA arena router symbol rename changed code")
        boot_code = Elf("build/boot.o").section_bytes(".text.boot")
        reserved_code = Elf("build/boot-reserved.o").section_bytes(".text.boot")
        persistent_code = Elf("build/boot-persistent.o").section_bytes(".text.boot")
        if len({sha(boot_code), sha(reserved_code), sha(persistent_code)}) != 3:
            raise ValueError("normal, reserved and nonvolatile boot transports must be distinct")
        for stem, expected_e820, expected_arena in (("e820-reserved", e820_code, arena_code),
                                                     ("e820-bypass", liar_code, arena_code),
                                                     ("e820-persistent", e820_code, arena_code),
                                                     ("e820-persistent-bypass", liar_code, arena_code),
                                                     ("arena-bypass", e820_code, liar_code)):
            linked64 = Elf("build/" + stem + ".elf")
            packed32 = Elf("build/" + stem + "-multiboot.elf")
            for symbol, expected_code in (("f0", code), ("e820_f0", expected_e820),
                                          ("arena_f0", expected_arena)):
                symbol_address = linked64.symbol(symbol)
                if packed32.symbol(symbol) != symbol_address:
                    raise ValueError(stem + " symbol differs after Multiboot wrapping")
                if (linked64.text_at(symbol_address, len(expected_code)) != expected_code or
                        packed32.text_at(symbol_address, len(expected_code)) != expected_code):
                    raise ValueError(stem + " lacks exact native HIA code for " + symbol)
        host = Elf("build/kernel-host.so")
        if host.section_bytes(".text") != code:
            raise ValueError("native library changed HIA code")
        inputs = [Path("Makefile")]
        for directory in ("src", "arch", "tests", "tools", "compatibility", ".github"):
            inputs.extend(p for p in Path(directory).rglob("*") if p.is_file()
                          and "__pycache__" not in p.parts and p.suffix != ".pyc")
        input_hashes = {str(p): sha(p.read_bytes()) for p in sorted(inputs)}
        artifacts = {str(p): sha(p.read_bytes()) for p in sorted(Path("build").glob("*"))
                     if p.suffix in (".o", ".so", ".elf", ".bin")}
        report.update(status="PASS", candidate_commit=os.environ.get("GITHUB_SHA"),
                      compiler_sha256=compiler_hash, hia_source_sha256=sha(source),
                      hia_object_sha256=sha(obj), hia_text_sha256=sha(code),
                      exact_source_recompiled_with_empty_PATH=True,
                      undefined_symbols=[], linked_hia_bytes_match=True,
                      multiboot_container_preserves_hia_bytes=True,
                      hia_entry_address=entry,
                      arena_router_source_sha256=sha(arena_source),
                      arena_router_object_sha256=sha(arena_object),
                      arena_router_exact_recompilation=True,
                      arena_router_loaded_text_matches=True,
                      arena_router_boot_entry=arena_entry,
                      arena_router_boot_code_matches=True,
                      arena_router_dishonest_mutant_rejected_by_tests=True,
                      e820_source_sha256=sha(e820_source),
                      e820_object_sha256=sha(e820_object),
                      e820_text_sha256=sha(e820_code),
                      e820_entry_address=e820_entry,
                      linked_hia_e820_bytes_match=True,
                      injected_reserved_boot_differs=True,
                      injected_nonvolatile_boot_differs=True,
                      nonvolatile_boot_contains_genuine_hia_e820=True,
                      nonvolatile_bypass_contains_dishonest_native_hia_e820=True,
                      reserved_boot_contains_genuine_hia_e820=True,
                      bypass_boot_contains_dishonest_native_hia_e820=True,
                      dishonest_e820_source_sha256=sha(liar_source),
                      dishonest_e820_object_sha256=sha(liar_object),
                      inputs=input_hashes, artifacts=artifacts,
                      input_manifest_sha256=sha(json.dumps(input_hashes, sort_keys=True,
                                                          separators=(",", ":")).encode()),
                      linker_version=subprocess.check_output(["ld", "--version"], text=True).splitlines()[0],
                      assembler_version=subprocess.check_output(["as", "--version"], text=True).splitlines()[0])
    except Exception as exc:
        report.update(status="FAIL", error=repr(exc))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("inputs", "artifacts")}, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
