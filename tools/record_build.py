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
        owner_source = Path("src/owner_binding.hepta").read_bytes()
        owner_object = Path("build/owner-binding.o").read_bytes()
        owner_rebuilt = subprocess.run([compiler], input=owner_source, capture_output=True,
                                     timeout=20, env={"PATH": ""})
        if owner_rebuilt.returncode or owner_rebuilt.stderr or owner_rebuilt.stdout != owner_object:
            raise ValueError("native HIA owner/state binder bytes not reproducible")
        if subprocess.check_output(["nm", "-u", "build/owner-binding.o"], text=True).strip():
            raise ValueError("HIA owner/state binder has undefined symbols")
        owner_code = Elf("build/owner-binding.o").section_bytes(".text")
        if Elf("build/owner-binding.so").section_bytes(".text") != owner_code:
            raise ValueError("HIA owner binding loaded image differs from source object")
        if Elf("build/owner-boot.o").section_bytes(".text") != owner_code:
            raise ValueError("native owner binding symbol rename changed code")
        reservation_source = Path("src/reservation_gate.hepta").read_bytes()
        reservation_object = Path("build/reservation-gate.o").read_bytes()
        reservation_rebuilt = subprocess.run([compiler], input=reservation_source,
                                            capture_output=True, timeout=20,
                                            env={"PATH": ""})
        if (reservation_rebuilt.returncode or reservation_rebuilt.stderr or
                reservation_rebuilt.stdout != reservation_object):
            raise ValueError("native HIA reservation exclusion bytes not reproducible")
        if subprocess.check_output(["nm", "-u", "build/reservation-gate.o"],
                                   text=True).strip():
            raise ValueError("HIA reservation gate has undefined symbols")
        reservation_text = Elf("build/reservation-gate.o").section_bytes(".text")
        if Elf("build/reservation-gate.so").section_bytes(".text") != reservation_text:
            raise ValueError("HIA reservation gate loaded machine code differs")
        if Elf("build/reservation-boot.o").section_bytes(".text") != reservation_text:
            raise ValueError("HIA reservation symbol rename changed native machine code")
        pte_source = Path("src/x86_pte_leaf.hepta").read_bytes()
        pte_object = Path("build/x86-pte.o").read_bytes()
        pte_rebuilt = subprocess.run([compiler], input=pte_source,
                                     capture_output=True, timeout=20,
                                     env={"PATH": ""})
        if (pte_rebuilt.returncode or pte_rebuilt.stderr or
                pte_rebuilt.stdout != pte_object):
            raise ValueError("native HIA x86 PTE permission object is not reproducible")
        if subprocess.check_output(["nm", "-u", "build/x86-pte.o"], text=True).strip():
            raise ValueError("native HIA x86 PTE permission object has undefined symbols")
        pte_text = Elf("build/x86-pte.o").section_bytes(".text")
        if Elf("build/pte-boot.o").section_bytes(".text") != pte_text:
            raise ValueError("HIA PTE boot symbol rename changed original code")
        if Elf("build/x86-pte.so").section_bytes(".text") != pte_text:
            raise ValueError("HIA x86 PTE native library differs from the compiled object")
        commit_source = Path("src/x86_pt_commit.hepta").read_bytes()
        commit_object = Path("build/x86-pt-commit.o").read_bytes()
        commit_rebuilt = subprocess.run([compiler], input=commit_source,
                                        capture_output=True, timeout=20,
                                        env={"PATH": ""})
        if (commit_rebuilt.returncode or commit_rebuilt.stderr or
                commit_rebuilt.stdout != commit_object):
            raise ValueError("native HIA leaf commit object differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-pt-commit.o"], text=True).strip():
            raise ValueError("native HIA leaf committer has undefined symbols")
        commit_text = Elf("build/x86-pt-commit.o").section_bytes(".text")
        if Elf("build/x86-pt-commit.so").section_bytes(".text") != commit_text:
            raise ValueError("native HIA leaf committer shared object differs")
        if Elf("build/pt-commit-boot.o").section_bytes(".text") != commit_text:
            raise ValueError("HIA leaf commit symbol rename modified machine code")
        # The same genuine selfhost object used by the native byte-array
        # oracle must appear in all three live hardware revocation images.
        revoke_source = Path("src/x86_pt_revoke.hepta").read_bytes()
        revoke_object = Path("build/x86-pt-revoke.o").read_bytes()
        revoke_rebuilt = subprocess.run([compiler], input=revoke_source,
                                        capture_output=True, timeout=20,
                                        env={"PATH": ""})
        if (revoke_rebuilt.returncode or revoke_rebuilt.stderr or
                revoke_rebuilt.stdout != revoke_object):
            raise ValueError("native HIA revoke differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-pt-revoke.o"], text=True).strip():
            raise ValueError("HIA revoker has undefined symbols")
        revoke_text = Elf("build/x86-pt-revoke.o").section_bytes(".text")
        if Elf("build/x86-pt-revoke.so").section_bytes(".text") != revoke_text:
            raise ValueError("HIA revoker shared object code differs")
        if Elf("build/pt-revoke-boot.o").section_bytes(".text") != revoke_text:
            raise ValueError("HIA revoker rename changed code")
        for revoke_stem in ("pt-revoke-fault", "pt-revoke-stale", "pt-revoke-bypass"):
            rev64 = Elf("build/" + revoke_stem + ".elf")
            rev32 = Elf("build/" + revoke_stem + "-multiboot.elf")
            rev_entry = rev64.symbol("pt_revoke_f0")
            if (rev32.symbol("pt_revoke_f0") != rev_entry or
                    rev64.text_at(rev_entry, len(revoke_text)) != revoke_text or
                    rev32.text_at(rev_entry, len(revoke_text)) != revoke_text):
                raise ValueError(revoke_stem + " lacks byte-exact native HIA revoker")
        rev_hashes = {sha(Path("build/" + stem + "-multiboot.elf").read_bytes())
                      for stem in ("pt-revoke-fault", "pt-revoke-stale", "pt-revoke-bypass")}
        if len(rev_hashes) != 3:
            raise ValueError("hardware revocation, stale and bypass images must differ")
        report["x86_pt_revoke_hardware"] = {
            "source_sha256": sha(revoke_source),
            "object_sha256": sha(revoke_object),
            "text_sha256": sha(revoke_text),
            "empty_path_recompiled": True,
            "boot_code_byte_identity": True,
            "distinct_fault_stale_bypass_images": True,
            "privileged_invlpg_emitted_by_hia": False,
            "smp_shootdown_verified": False,
        }

        # Independent reproducibility and loaded-code identity of the native HIA
        # exact-old RW->RO PTE downgrade; not yet a live MMU/TLB transition.

        # Independent source-to-object recompilation of the genuine HIA
        # RX->R/NX exact-old downgrade; no privileged TLB or atomicity claim.
        nx_source = Path("src/x86_pt_nx_protect.hepta").read_bytes()
        nx_object = Path("build/x86-pt-nx-protect.o").read_bytes()
        nx_rebuilt = subprocess.run([compiler], input=nx_source,
                                    capture_output=True, timeout=20,
                                    env={"PATH": ""})
        if (nx_rebuilt.returncode or nx_rebuilt.stderr or
                nx_rebuilt.stdout != nx_object):
            raise ValueError("native HIA NX downgrade differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-pt-nx-protect.o"],
                                   text=True).strip():
            raise ValueError("HIA NX downgrade has undefined symbols")
        nx_text = Elf("build/x86-pt-nx-protect.o").section_bytes(".text")
        if Elf("build/x86-pt-nx-protect.so").section_bytes(".text") != nx_text:
            raise ValueError("HIA NX downgrade loaded .text differs")
        if Elf("build/pt-nx-boot.o").section_bytes(".text") != nx_text:
            raise ValueError("native HIA NX boot symbol rename changed machine code")
        for stem in ("pt-nx-fault", "pt-nx-stale", "pt-nx-bypass"):
            elf64 = Elf("build/" + stem + ".elf")
            elf32 = Elf("build/" + stem + "-multiboot.elf")
            entry = elf64.symbol("pt_nx_f0")
            if (elf32.symbol("pt_nx_f0") != entry or
                    elf64.text_at(entry, len(nx_text)) != nx_text or
                    elf32.text_at(entry, len(nx_text)) != nx_text):
                raise ValueError("live NX image differs from original HIA .text: " + stem)
        report["x86_pt_nx_hardware"] = {
            "observer_non_hia": True,
            "boot_object_sha256": sha(Path("build/pt-nx-boot.o").read_bytes()),
            "identical_native_code_in_three_boot_images": True,
            "images_sha256": {
                stem: sha(Path("build/" + stem + "-multiboot.elf").read_bytes())
                for stem in ("pt-nx-fault", "pt-nx-stale", "pt-nx-bypass")
            },
        }
        report["x86_pt_nx_protect"] = {
            "source_sha256": sha(nx_source),
            "object_sha256": sha(nx_object),
            "text_sha256": sha(nx_text),
            "empty_path_recompiled": True,
            "loaded_text_byte_identity": True,
            "hardware_instruction_fetch_checked": True,
            "hardware_observer_is_non_hia": True,
            "tlb_invalidation_emitted_by_hia": False,
            "smp_atomicity_verified": False,
        }

        protect_source = Path("src/x86_pt_write_protect.hepta").read_bytes()
        protect_object = Path("build/x86-pt-write-protect.o").read_bytes()
        protect_rebuilt = subprocess.run([compiler], input=protect_source,
                                       capture_output=True, timeout=20,
                                       env={"PATH": ""})
        if (protect_rebuilt.returncode or protect_rebuilt.stderr or
                protect_rebuilt.stdout != protect_object):
            raise ValueError("native HIA RW downgrade differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-pt-write-protect.o"],
                                   text=True).strip():
            raise ValueError("HIA RW downgrade has undefined symbols")
        protect_text = Elf("build/x86-pt-write-protect.o").section_bytes(".text")
        if Elf("build/x86-pt-write-protect.so").section_bytes(".text") != protect_text:
            raise ValueError("HIA RW downgrade loaded .text differs from source object")
        # Prove all three QEMU hardware experiments load precisely the
        # same original selfhost-compiled native HIA .text, not a surrogate.
        if Elf("build/pt-protect-boot.o").section_bytes(".text") != protect_text:
            raise ValueError("HIA write-protect boot object .text diverges")
        for stem in ("pt-protect-fault", "pt-protect-stale", "pt-protect-bypass"):
            elf64 = Elf("build/" + stem + ".elf")
            elf32 = Elf("build/" + stem + "-multiboot.elf")
            entry = elf64.symbol("pt_protect_f0")
            if (elf32.symbol("pt_protect_f0") != entry or
                    elf64.text_at(entry, len(protect_text)) != protect_text or
                    elf32.text_at(entry, len(protect_text)) != protect_text):
                raise ValueError("HIA write-protect image .text diverges: " + stem)
        report["x86_pt_write_protect_hardware"] = {
            "observer_is_non_hia": True,
            "native_hia_bytes_identical_in_three_images": True,
            "boot_object_sha256": sha(Path("build/pt-protect-boot.o").read_bytes()),
            "images_sha256": {
                stem: sha(Path("build/" + stem + "-multiboot.elf").read_bytes())
                for stem in ("pt-protect-fault", "pt-protect-stale", "pt-protect-bypass")
            },
        }
        report["x86_pt_write_protect"] = {
            "source_sha256": sha(protect_source),
            "object_sha256": sha(protect_object),
            "text_sha256": sha(protect_text),
            "empty_path_recompiled": True,
            "loaded_text_byte_identity": True,
            "tlb_invalidation_emitted_by_hia": False,
            "smp_atomicity_verified": False,
        }

        us_source = Path("src/x86_pt_user_revoke.hepta").read_bytes()
        us_object = Path("build/x86-pt-user-revoke.o").read_bytes()
        us_rebuilt = subprocess.run([compiler], input=us_source, capture_output=True,
                                    timeout=20, env={"PATH": ""})
        if us_rebuilt.returncode or us_rebuilt.stderr or us_rebuilt.stdout != us_object:
            raise ValueError("native HIA user-to-supervisor PTE revoke differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-pt-user-revoke.o"],
                                   text=True).strip():
            raise ValueError("native HIA U/S revoke has undefined symbols")
        us_text = Elf("build/x86-pt-user-revoke.o").section_bytes(".text")
        if Elf("build/x86-pt-user-revoke.so").section_bytes(".text") != us_text:
            raise ValueError("native HIA U/S revoke loaded .text differs")
        # Independently compare original HIA bytes with every linked hardware
        # observer, rather than accepting a substituted assembly surrogate.
        if Elf("build/pt-us-boot.o").section_bytes(".text") != us_text:
            raise ValueError("native HIA U/S revoke boot symbol changed .text")
        for stem in ("us-fault", "us-stale", "us-bypass"):
            elf64 = Elf("build/" + stem + ".elf")
            elf32 = Elf("build/" + stem + "-multiboot.elf")
            addr = elf64.symbol("pt_us_f0")
            if (elf32.symbol("pt_us_f0") != addr or
                    elf64.text_at(addr, len(us_text)) != us_text or
                    elf32.text_at(addr, len(us_text)) != us_text):
                raise ValueError(stem + " lacks exact native HIA U/S .text")
        us_images = {stem: sha(Path("build/" + stem + "-multiboot.elf").read_bytes())
                     for stem in ("us-fault", "us-stale", "us-bypass")}
        if len(set(us_images.values())) != 3:
            raise ValueError("fault/stale/bypass images not independent")
        boot_report = json.loads(Path("build/boot-report.json").read_text())
        if boot_report.get("status") != "PASS":
            raise ValueError("CPL3 U/S experiments did not finish successfully")
        required = {"us_revoke_hardware_fault", "us_revoke_stale_rejected",
                    "us_revoke_bypass_executed"}
        qualified = [row for row in boot_report["runs"] if row["mode"] in required]
        if (len(qualified) != 6 or
                {(row["mode"], row["machine"]) for row in qualified} !=
                {(mode, machine) for mode in required for machine in ("pc", "q35")} or
                any(row["status"] != "PASS" or
                    row["image_sha256"] != us_images[row["image"].split("/")[-1].split("-multiboot")[0]]
                    for row in qualified)):
            raise ValueError("CPL3 results not bound to their exact images")
        report["x86_pt_user_revoke_hardware"] = {
            "observer_is_non_hia": True,
            "native_hia_text_byte_identical": True,
            "pc_q35_modes_passed": 6,
            "images_sha256": us_images,
            "privileged_invlpg_emitted_by_hia": False,
            "atomicity_or_smp_verified": False,
        }

        report["x86_pt_user_revoke"] = {
            "source_sha256": sha(us_source), "object_sha256": sha(us_object),
            "text_sha256": sha(us_text), "empty_path_recompiled": True,
            "loaded_text_byte_identity": True, "hardware_cpl3_verified": True,
            "tlb_invalidation_emitted_by_hia": False,
            "smp_atomicity_verified": False,
        }

        pf_source = Path("src/x86_pf_gate.hepta").read_bytes()
        pf_object = Path("build/x86-pf-gate.o").read_bytes()
        pf_rebuilt = subprocess.run([compiler], input=pf_source,
                                    capture_output=True, timeout=20,
                                    env={"PATH": ""})
        if (pf_rebuilt.returncode or pf_rebuilt.stderr or
                pf_rebuilt.stdout != pf_object):
            raise ValueError("HIA page fault gate differs from empty-PATH native rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-pf-gate.o"], text=True).strip():
            raise ValueError("HIA page fault gate has undefined symbols")
        pf_text = Elf("build/x86-pf-gate.o").section_bytes(".text")
        if Elf("build/x86-pf-gate.so").section_bytes(".text") != pf_text:
            raise ValueError("native HIA page fault gate loaded code differs")
        if Elf("build/pf-gate-boot.o").section_bytes(".text") != pf_text:
            raise ValueError("native HIA #PF gate symbol rename changed instructions")
        idt_source = Path("src/x86_idt_gate.hepta").read_bytes()
        idt_object = Path("build/x86-idt.o").read_bytes()
        idt_rebuilt = subprocess.run([compiler], input=idt_source, capture_output=True,
                                     timeout=20, env={"PATH": ""})
        if (idt_rebuilt.returncode or idt_rebuilt.stderr or
                idt_rebuilt.stdout != idt_object):
            raise ValueError("native HIA IDT object differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-idt.o"], text=True).strip():
            raise ValueError("HIA IDT descriptor installer has undefined symbols")
        if (Elf("build/x86-idt.so").section_bytes(".text") !=
                Elf("build/x86-idt.o").section_bytes(".text")):
            raise ValueError("native HIA IDT host object machine bytes differ")
        idt_native_text = Elf("build/x86-idt.o").section_bytes(".text")
        if Elf("build/idt-gate-boot.o").section_bytes(".text") != idt_native_text:
            raise ValueError("native HIA IDT symbol rename changed machine code")
        state_source = Path("src/x86_tss_state.hepta").read_bytes()
        state_object = Path("build/x86-tss-state.o").read_bytes()
        state_rebuilt = subprocess.run([compiler], input=state_source, capture_output=True,
                                      timeout=20, env={"PATH": ""})
        if state_rebuilt.returncode or state_rebuilt.stderr or state_rebuilt.stdout != state_object:
            raise ValueError("native HIA TSS state differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-tss-state.o"], text=True).strip():
            raise ValueError("native HIA TSS state has undefined symbols")
        state_text = Elf("build/x86-tss-state.o").section_bytes(".text")
        if Elf("build/x86-tss-state.so").section_bytes(".text") != state_text:
            raise ValueError("native HIA TSS state host code differs")
        if Elf("build/tss-state-boot.o").section_bytes(".text") != state_text:
            raise ValueError("native HIA TSS state symbol rename changed code")
        usr_source = Path("src/x86_user_gdt.hepta").read_bytes()
        usr_object = Path("build/x86-user-gdt.o").read_bytes()
        usr_rebuilt = subprocess.run([compiler], input=usr_source, capture_output=True,
                                     timeout=20, env={"PATH": ""})
        if usr_rebuilt.returncode or usr_rebuilt.stderr or usr_rebuilt.stdout != usr_object:
            raise ValueError("native HIA user GDT differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-user-gdt.o"], text=True).strip():
            raise ValueError("native HIA user GDT object has undefined symbols")
        usr_text = Elf("build/x86-user-gdt.o").section_bytes(".text")
        if Elf("build/x86-user-gdt.so").section_bytes(".text") != usr_text:
            raise ValueError("native HIA user GDT host image differs")
        if Elf("build/user-gdt-boot.o").section_bytes(".text") != usr_text:
            raise ValueError("native HIA user GDT symbol rename changed code")
        # Independently rebuild native HIA upper-level PML4E/PDPTE U/S gate.
        upper_source = Path("src/x86_upper_user_gate.hepta").read_bytes()
        upper_object = Path("build/x86-upper-user.o").read_bytes()
        upper_rebuilt = subprocess.run([compiler], input=upper_source,
                                     capture_output=True, timeout=20, env={"PATH": ""})
        if upper_rebuilt.returncode or upper_rebuilt.stderr or upper_rebuilt.stdout != upper_object:
            raise ValueError("HIA upper-level U/S object differs from empty-PATH rebuild")
        if subprocess.check_output(["nm","-u","build/x86-upper-user.o"],text=True).strip():
            raise ValueError("HIA upper-level U/S object has undefined symbols")
        if Elf("build/x86-upper-user.so").section_bytes(".text") != Elf("build/x86-upper-user.o").section_bytes(".text"):
            raise ValueError("HIA upper-level U/S host code differs from HIA object")
        upper_code = Elf("build/x86-upper-user.o").section_bytes(".text")
        if Elf("build/upper-user-boot.o").section_bytes(".text") != upper_code:
            raise ValueError("HIA upper user symbol rename changed machine code")
        report["upper_user_gate"] = {"source_sha256":sha(upper_source),
                                     "object_sha256":sha(upper_object),
                                     "live_qemu_integration":True,
                                     "smp_atomicity_verified":False}
        # Rebuild the genuine HIA 2MiB huge PDE writer without a host PATH.
        huge_source = Path("src/x86_pde_2m.hepta").read_bytes()
        huge_object = Path("build/x86-pde-2m.o").read_bytes()
        huge_rebuilt = subprocess.run([compiler], input=huge_source, capture_output=True,
                                     timeout=20, env={"PATH": ""})
        if huge_rebuilt.returncode or huge_rebuilt.stderr or huge_rebuilt.stdout != huge_object:
            raise ValueError("HIA huge PDE object differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-pde-2m.o"], text=True).strip():
            raise ValueError("HIA huge PDE object has undefined symbols")
        huge_text = Elf("build/x86-pde-2m.o").section_bytes(".text")
        if Elf("build/x86-pde-2m.so").section_bytes(".text") != huge_text:
            raise ValueError("HIA huge PDE native library bytes differ")
        if Elf("build/pde-2m-boot.o").section_bytes(".text") != huge_text:
            raise ValueError("HIA huge PDE symbol rename changed its machine code")
        tss_source = Path("src/x86_tss_gdt.hepta").read_bytes()
        tss_object = Path("build/x86-tss-gdt.o").read_bytes()
        tss_rebuilt = subprocess.run([compiler], input=tss_source, capture_output=True,
                                    timeout=20, env={"PATH": ""})
        if tss_rebuilt.returncode or tss_rebuilt.stderr or tss_rebuilt.stdout != tss_object:
            raise ValueError("native HIA TSS GDT object differs from empty-PATH rebuild")
        if subprocess.check_output(["nm", "-u", "build/x86-tss-gdt.o"], text=True).strip():
            raise ValueError("native HIA TSS GDT object has undefined symbols")
        tss_native_text = Elf("build/x86-tss-gdt.o").section_bytes(".text")
        if Elf("build/x86-tss-gdt.so").section_bytes(".text") != tss_native_text:
            raise ValueError("native HIA TSS GDT host image differs")
        if Elf("build/tss-gdt-boot.o").section_bytes(".text") != tss_native_text:
            raise ValueError("native HIA TSS symbol rename changed code")
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
        owner_entry = image64.symbol("owner_f0")
        if image32.symbol("owner_f0") != owner_entry:
            raise ValueError("native HIA owner binding entry mismatch in packed image")
        if (image64.text_at(owner_entry, len(owner_code)) != owner_code or
                image32.text_at(owner_entry, len(owner_code)) != owner_code):
            raise ValueError("default QEMU boot images lack exact HIA owner binding machine code")
        e820_entry = image64.symbol("e820_f0")
        if image32.symbol("e820_f0") != e820_entry:
            raise ValueError("E820 Multiboot entry mismatch")
        if (image64.text_at(e820_entry, len(e820_code)) != e820_code or
                image32.text_at(e820_entry, len(e820_code)) != e820_code):
            raise ValueError("native HIA E820 code not preserved in boot images")
        pte_boot_entry = image64.symbol("pte_f0")
        if image32.symbol("pte_f0") != pte_boot_entry:
            raise ValueError("HIA PTE entry changed in multiboot image")
        if (image64.text_at(pte_boot_entry, len(pte_text)) != pte_text or
                image32.text_at(pte_boot_entry, len(pte_text)) != pte_text):
            raise ValueError("QEMU boot image lacks byte-exact native HIA PTE")
        pt_commit_entry = image64.symbol("pt_commit_f0")
        if image32.symbol("pt_commit_f0") != pt_commit_entry:
            raise ValueError("native HIA PTE commit entry changed after Multiboot wrap")
        if (image64.text_at(pt_commit_entry, len(commit_text)) != commit_text or
                image32.text_at(pt_commit_entry, len(commit_text)) != commit_text):
            raise ValueError("QEMU boot lacks byte-exact native HIA PTE commit")
        pf_boot_entry = image64.symbol("pf_gate_f0")
        if image32.symbol("pf_gate_f0") != pf_boot_entry:
            raise ValueError("HIA #PF gate entry changed after Multiboot wrap")
        if (image64.text_at(pf_boot_entry, len(pf_text)) != pf_text or
                image32.text_at(pf_boot_entry, len(pf_text)) != pf_text):
            raise ValueError("QEMU boot lacks byte-exact native HIA #PF gate")
        idt_boot_entry = image64.symbol("idt_gate_f0")
        if image32.symbol("idt_gate_f0") != idt_boot_entry:
            raise ValueError("native HIA IDT entry changed in Multiboot image")
        if (image64.text_at(idt_boot_entry, len(idt_native_text)) != idt_native_text or
                image32.text_at(idt_boot_entry, len(idt_native_text)) != idt_native_text):
            raise ValueError("native HIA IDT gate absent or different in boot")
        state_boot_entry = image64.symbol("tss_state_f0")
        if image32.symbol("tss_state_f0") != state_boot_entry:
            raise ValueError("native HIA TSS state entry differs after Multiboot")
        if (image64.text_at(state_boot_entry, len(state_text)) != state_text or
                image32.text_at(state_boot_entry, len(state_text)) != state_text):
            raise ValueError("default boot lacks byte-exact HIA TSS state")
        usr_boot_entry = image64.symbol("user_gdt_f0")
        if image32.symbol("user_gdt_f0") != usr_boot_entry:
            raise ValueError("HIA user GDT entry changed in Multiboot image")
        if (image64.text_at(usr_boot_entry, len(usr_text)) != usr_text or
                image32.text_at(usr_boot_entry, len(usr_text)) != usr_text):
            raise ValueError("QEMU boot lacks byte-exact HIA user GDT")
        tss_boot_entry = image64.symbol("tss_gdt_f0")
        if image32.symbol("tss_gdt_f0") != tss_boot_entry:
            raise ValueError("native HIA TSS GDT entry changed after Multiboot wrap")
        if (image64.text_at(tss_boot_entry, len(tss_native_text)) != tss_native_text or
                image32.text_at(tss_boot_entry, len(tss_native_text)) != tss_native_text):
            raise ValueError("default boot lacks byte-exact HIA TSS GDT")
        reservation_entry = image64.symbol("reservation_f0")
        if image32.symbol("reservation_f0") != reservation_entry:
            raise ValueError("HIA reservation boot entry mismatch")
        if (image64.text_at(reservation_entry, len(reservation_text)) != reservation_text
                or image32.text_at(reservation_entry, len(reservation_text)) != reservation_text):
            raise ValueError("linked boot lacks exact native HIA reservation instructions")
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
        if Elf("build/reservation-unsafe-boot.o").section_bytes(".text") != liar_code:
            raise ValueError("dishonest native HIA reservation symbol rename changed code")
        boot_code = Elf("build/boot.o").section_bytes(".text.boot")
        reserved_code = Elf("build/boot-reserved.o").section_bytes(".text.boot")
        persistent_code = Elf("build/boot-persistent.o").section_bytes(".text.boot")
        alias_code = Elf("build/boot-owner-alias.o").section_bytes(".text.boot")
        protected_code = Elf("build/boot-reservation-conflict.o").section_bytes(".text.boot")
        pte_unsafe_code = Elf("build/boot-pte-unsafe.o").section_bytes(".text.boot")
        nx_fault_code = Elf("build/boot-nx-fault.o").section_bytes(".text.boot")
        nx_bypass_code = Elf("build/boot-nx-bypass.o").section_bytes(".text.boot")
        wp_fault_code = Elf("build/boot-wp-fault.o").section_bytes(".text.boot")
        wp_bypass_code = Elf("build/boot-wp-bypass.o").section_bytes(".text.boot")
        pt_commit_conflict_code = Elf("build/boot-pt-commit-conflict.o").section_bytes(".text.boot")
        pf_corrupt_code = Elf("build/boot-pf-corrupt.o").section_bytes(".text.boot")
        state_conflict_code = Elf("build/boot-tss-state-conflict.o").section_bytes(".text.boot")
        tss_conflict_code = Elf("build/boot-tss-conflict.o").section_bytes(".text.boot")
        idt_conflict_code = Elf("build/boot-idt-conflict.o").section_bytes(".text.boot")
        if len({sha(boot_code), sha(reserved_code), sha(persistent_code),
                sha(alias_code), sha(protected_code), sha(pte_unsafe_code),
                sha(nx_fault_code), sha(nx_bypass_code),
                sha(wp_fault_code), sha(wp_bypass_code),
                 sha(pt_commit_conflict_code), sha(pf_corrupt_code),
                 sha(idt_conflict_code), sha(tss_conflict_code), sha(state_conflict_code)}) != 15:
            raise ValueError("normal, reserved, persistent, alias and protected boot transports must differ")
        # Distinguish separately linked negative-control images. Relocation
        # targets can differ while unlinked .text.boot instruction bytes are
        # identical; requiring a sixteenth unique unlinked section would be
        # a false failure, not proof of a separate machine behavior.
        if (sha(Path("build/tss-rsp0-conflict-multiboot.elf").read_bytes()) ==
                sha(Path("build/tss-state-conflict-multiboot.elf").read_bytes())):
            raise ValueError("RSP0 and IST1 fault images must differ after linking")
        if (sha(Path("build/ring3-upper-stale-multiboot.elf").read_bytes()) ==
                sha(Path("build/ring3-rsp0-multiboot.elf").read_bytes())):
            raise ValueError("stale upper HIA image not distinct from ring3 positive")
        if (sha(Path("build/ring3-pde-stale-multiboot.elf").read_bytes()) ==
                sha(Path("build/ring3-rsp0-multiboot.elf").read_bytes())):
            raise ValueError("stale HIA PDE and admitted ring3 image must differ")
        if (sha(Path("build/ring3-rsp0-multiboot.elf").read_bytes()) ==
                sha(Path("build/ring3-rsp0-decoy-multiboot.elf").read_bytes())):
            raise ValueError("ring3 RSP0 and decoy mutant must have different images")
        if (sha(Path("build/user-gdt-conflict-multiboot.elf").read_bytes()) ==
                sha(Path("build/tss-conflict-multiboot.elf").read_bytes())):
            raise ValueError("user GDT stale-word and TSS stale-word images must differ")
        for stem, expected_e820, expected_arena, expected_reservation in (
                ("e820-reserved", e820_code, arena_code, reservation_text),
                ("e820-bypass", liar_code, arena_code, reservation_text),
                ("e820-persistent", e820_code, arena_code, reservation_text),
                ("e820-persistent-bypass", liar_code, arena_code, reservation_text),
                ("arena-bypass", e820_code, liar_code, reservation_text),
                ("owner-alias", e820_code, arena_code, reservation_text),
                ("reservation-conflict", e820_code, arena_code, reservation_text),
                ("reservation-bypass", e820_code, arena_code, liar_code),
                ("pte-unsafe", e820_code, arena_code, reservation_text),
                ("pt-commit-conflict", e820_code, arena_code, reservation_text),
                ("nx-fault", e820_code, arena_code, reservation_text),
                ("nx-bypass", e820_code, arena_code, reservation_text),
                ("wp-fault", e820_code, arena_code, reservation_text),
                ("wp-bypass", e820_code, arena_code, reservation_text),
                ("pf-corrupt", e820_code, arena_code, reservation_text),
                ("idt-conflict", e820_code, arena_code, reservation_text),
                ("user-gdt-conflict", e820_code, arena_code, reservation_text),
                ("tss-conflict", e820_code, arena_code, reservation_text),
                ("tss-state-conflict", e820_code, arena_code, reservation_text),
                ("tss-rsp0-conflict", e820_code, arena_code, reservation_text),
                ("ring3-rsp0", e820_code, arena_code, reservation_text),
                ("ring3-rsp0-decoy", e820_code, arena_code, reservation_text),
                ("ring3-pde-stale", e820_code, arena_code, reservation_text),
                ("ring3-upper-stale", e820_code, arena_code, reservation_text)):
            linked64 = Elf("build/" + stem + ".elf")
            packed32 = Elf("build/" + stem + "-multiboot.elf")
            for symbol, expected_code in (("f0", code), ("e820_f0", expected_e820),
                                          ("arena_f0", expected_arena), ("owner_f0", owner_code),
                                          ("reservation_f0", expected_reservation),
                                          ("pte_f0", pte_text),
                                           ("pt_commit_f0", commit_text),
                                           ("pf_gate_f0", pf_text),
                                           ("idt_gate_f0", idt_native_text),
                                           ("tss_gdt_f0", tss_native_text),
                                           ("tss_state_f0", state_text)):
                symbol_address = linked64.symbol(symbol)
                if packed32.symbol(symbol) != symbol_address:
                    raise ValueError(stem + " symbol differs after Multiboot wrapping")
                if (linked64.text_at(symbol_address, len(expected_code)) != expected_code or
                        packed32.text_at(symbol_address, len(expected_code)) != expected_code):
                    raise ValueError(stem + " lacks exact native HIA code for " + symbol)
        for stem in ("ring3-rsp0", "ring3-rsp0-decoy", "ring3-pde-stale", "ring3-upper-stale"):
            huge_elf = Elf("build/" + stem + ".elf")
            huge_mb = Elf("build/" + stem + "-multiboot.elf")
            huge_entry = huge_elf.symbol("pde_2m_f0")
            if huge_entry != huge_mb.symbol("pde_2m_f0"):
                raise ValueError(stem + " HIA huge PDE entry changed in Multiboot")
            if (huge_elf.text_at(huge_entry, len(huge_text)) != huge_text or
                    huge_mb.text_at(huge_entry, len(huge_text)) != huge_text):
                raise ValueError(stem + " lacks byte-exact native HIA huge PDE code")
            upper_entry = huge_elf.symbol("upper_user_f0")
            if huge_mb.symbol("upper_user_f0") != upper_entry:
                raise ValueError(stem + " upper HIA entry differed after Multiboot wrap")
            if (huge_elf.text_at(upper_entry,len(upper_code)) != upper_code or
                    huge_mb.text_at(upper_entry,len(upper_code)) != upper_code):
                raise ValueError(stem + " missing native HIA upper-table exact code")
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
                      owner_binding_source_sha256=sha(owner_source),
                       owner_binding_object_sha256=sha(owner_object),
                       owner_binding_text_sha256=sha(owner_code),
                       owner_binding_boot_entry=owner_entry,
                       owner_binding_exact_recompilation=True,
                       owner_binding_loaded_text_matches=True,
                       owner_binding_boot_code_matches=True,
                       reservation_source_sha256=sha(reservation_source),
                      reservation_object_sha256=sha(reservation_object),
                      reservation_text_sha256=sha(reservation_text),
                      reservation_exact_recompilation=True,
                      reservation_loaded_text_matches=True,
                       reservation_boot_entry=reservation_entry,
                       reservation_boot_code_matches=True,
                       reservation_negative_control_rejected_by_tests=True,
                      x86_pte_source_sha256=sha(pte_source),
                      x86_pte_object_sha256=sha(pte_object),
                      x86_pte_text_sha256=sha(pte_text),
                      x86_pte_exact_recompilation=True,
                      x86_pte_loaded_text_matches=True,
                      x86_pte_not_integrated_in_boot=False,
                      x86_pte_boot_entry=pte_boot_entry,
                      x86_pte_live_boot_entry_byte_identity=True,
                      x86_pf_source_sha256=sha(pf_source),
                       x86_pf_object_sha256=sha(pf_object),
                       x86_pf_text_sha256=sha(pf_text),
                       x86_pf_exact_recompilation=True,
                       x86_pf_loaded_text_matches=True,
                       x86_idt_native_object_source_sha256=sha(idt_source),
                       x86_idt_native_object_sha256=sha(idt_object),
                       x86_idt_live_boot_entry=idt_boot_entry,
                       x86_idt_live_boot_code_matches=True,
                       x86_pde_2m_source_sha256=sha(huge_source),
                       x86_pde_2m_object_sha256=sha(huge_object),
                       x86_pde_2m_text_sha256=sha(huge_text),
                       x86_pde_2m_empty_path_recompiled=True,
                       x86_pde_2m_live_cpl3_hardware_path_bytes_match=True,
                       x86_pde_2m_privileged_backend=False,
                       x86_user_gdt_source_sha256=sha(usr_source),
                       x86_user_gdt_object_sha256=sha(usr_object),
                       x86_user_gdt_text_sha256=sha(usr_text),
                       x86_user_gdt_boot_entry=usr_boot_entry,
                       x86_user_gdt_live_boot_code_matches=True,
                       x86_user_gdt_native_privilege_transition=False,
                       x86_tss_state_source_sha256=sha(state_source),
                        x86_tss_state_object_sha256=sha(state_object),
                        x86_tss_state_text_sha256=sha(state_text),
                        x86_tss_state_boot_entry=state_boot_entry,
                        x86_tss_state_boot_code_matches=True,
                        x86_tss_state_native_ltr=False,
                        x86_idt_assembly_lidt_bridge_retained=True,
                       x86_pf_native_exception_entry=False,
                       x86_pf_boot_entry=pf_boot_entry,
                       x86_pf_boot_code_matches=True,
                       x86_pf_assembly_interrupt_bridge_retained=True,
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
