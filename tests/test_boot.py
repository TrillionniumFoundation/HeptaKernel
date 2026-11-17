#!/usr/bin/env python3
"""Run the genuine boot image and two independently broken HIA kernels."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PASS_MARKER = "HEPTAKERNEL HIA PMM PASS"
FAIL_MARKER = "HEPTAKERNEL BOOT FAIL"
MAP_MARKER = "HEPTAKERNEL HIA E820 VERIFIED"
IDT_MARKER = "HEPTAKERNEL HIA LIVE IDT VERIFIED"
TSS_STATE_MARKER = "HEPTAKERNEL HIA LIVE TSS STATE VERIFIED"
TSS_STATE_STALE_MARKER = "HEPTAKERNEL HIA TSS STATE STALE WORD REJECTED"
TSS_MARKER = "HEPTAKERNEL HIA LIVE TSS GDT VERIFIED"
TSS_STALE_MARKER = "HEPTAKERNEL HIA TSS GDT STALE WORD REJECTED"
IDT_STALE_MARKER = "HEPTAKERNEL HIA IDT STALE WORD REJECTED"
IST_MARKER = "HEPTAKERNEL HIA IDT IST1 HARDWARE STACK VERIFIED"
RESERVATION_MARKER = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
ROUTER_MARKER = "HEPTAKERNEL HIA ARENA ROUTER VERIFIED"
OWNER_MARKER = "HEPTAKERNEL HIA MULTI-ARENA OWNERSHIP VERIFIED"
PTE_MARKER = "HEPTAKERNEL HIA LIVE PTE VERIFIED"
PT_COMMIT_MARKER = "HEPTAKERNEL HIA PT COMMIT VERIFIED"
PF_MARKER = "HEPTAKERNEL HIA PF RECORD ADMITTED"
NX_FAULT_MARKER = "HEPTAKERNEL HIA NX FETCH FAULT VERIFIED"
NX_BYPASS_MARKER = "HEPTAKERNEL HIA NX BYPASS EXECUTED"
WP_FAULT_MARKER = "HEPTAKERNEL HIA SUPERVISOR WRITE-PROTECT FAULT VERIFIED"
WP_BYPASS_MARKER = "HEPTAKERNEL HIA WRITE-PROTECT BYPASS STORED"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(qemu, image, machine="pc", memory="32", mode="positive"):
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", "qemu64", "-m", memory,
           "-nodefaults", "-display", "none", "-serial", "stdio", "-monitor", "none",
           "-no-reboot", "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
           "-kernel", str(image)]
    record = {"image": str(image), "image_sha256": digest(image), "machine": machine,
              "memory_mib": int(memory), "mode": mode, "positive": mode == "positive", "command": cmd}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        record.update(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        state_verified = p.stdout.count(TSS_STATE_MARKER) == 1
        state_stale = p.stdout.count(TSS_STATE_STALE_MARKER) == 1
        record["native_hia_tss_state_observed"] = state_verified
        record["native_hia_tss_state_stale_observed"] = state_stale
        tss_verified = p.stdout.count(TSS_MARKER) == 1
        tss_stale = p.stdout.count(TSS_STALE_MARKER) == 1
        record['native_hia_tss_gdt_observed'] = tss_verified
        record['native_hia_tss_stale_refusal_observed'] = tss_stale
        idt_verified = p.stdout.count(IDT_MARKER) == 1
        idt_stale_rejected = p.stdout.count(IDT_STALE_MARKER) == 1
        ist_fault_verified = p.stdout.count(IST_MARKER) == 1
        record["real_ist1_exception_stack_observed"] = ist_fault_verified
        record["native_hia_live_idt_observed"] = idt_verified
        record["native_hia_idt_stale_refusal_observed"] = idt_stale_rejected
        map_verified = p.stdout.count(MAP_MARKER) == 1
        record["native_hia_e820_gate_observed"] = map_verified
        reservation_verified = p.stdout.count(RESERVATION_MARKER) == 1
        record["native_hia_reservation_gate_observed"] = reservation_verified
        pte_verified = p.stdout.count(PTE_MARKER) == 1
        pt_commit_verified = p.stdout.count(PT_COMMIT_MARKER) == 1
        record["native_hia_pt_commit_observed"] = pt_commit_verified
        pf_admitted = p.stdout.count(PF_MARKER) == 1
        record["native_hia_fault_record_admitted"] = pf_admitted
        record["native_hia_live_pte_observed"] = pte_verified
        nx_fault_verified = p.stdout.count(NX_FAULT_MARKER) == 1
        nx_bypass_executed = p.stdout.count(NX_BYPASS_MARKER) == 1
        wp_fault_verified = p.stdout.count(WP_FAULT_MARKER) == 1
        wp_bypass_executed = p.stdout.count(WP_BYPASS_MARKER) == 1
        record["hardware_nx_fetch_fault_verified"] = nx_fault_verified
        record["mutated_nx_bypass_executed"] = nx_bypass_executed
        record["hardware_supervisor_write_protect_fault_verified"] = wp_fault_verified
        record["mutated_write_protect_bypass_executed"] = wp_bypass_executed
        route_verified = p.stdout.count(ROUTER_MARKER) == 1
        record["native_hia_arena_router_observed"] = route_verified
        owner_verified = p.stdout.count(OWNER_MARKER) == 1
        record["native_hia_multizone_state_and_readback_observed"] = owner_verified
        if mode == "tss_state_conflict_rejected":
            accepted = (state_stale and not state_verified and not tss_verified and
                        not idt_verified and not map_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "tss_gdt_conflict_rejected":
            accepted = (tss_stale and not tss_verified and not idt_verified and
                        not map_verified and not reservation_verified and
                        p.returncode == 35 and FAIL_MARKER in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "idt_conflict_rejected":
            accepted = (not idt_verified and idt_stale_rejected and
                        not map_verified and not reservation_verified and
                        not pte_verified and not pt_commit_verified and
                        not route_verified and not owner_verified and
                        p.returncode == 35 and FAIL_MARKER in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "positive":
            accepted = (map_verified and reservation_verified and pte_verified and route_verified and owner_verified and p.returncode == 33 and
                        p.stdout.count(PASS_MARKER) == 1 and FAIL_MARKER not in p.stdout)
        elif mode == "allocator_negative":
            # Wrong allocator must fail after the genuine HIA map gate.
            accepted = (map_verified and reservation_verified and pte_verified and route_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "owner_alias_negative":
            accepted = (map_verified and reservation_verified and pte_verified and route_verified and not owner_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "arena_router_negative":
            # Genuine E820 accepts the map, but the fraudulent native HIA
            # router must fail the independent first fixture before PMM access.
            accepted = (map_verified and reservation_verified and pte_verified and not route_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "nx_hardware_fault":
            accepted = (map_verified and reservation_verified and not pte_verified and
                        nx_fault_verified and ist_fault_verified and not nx_bypass_executed and not route_verified and
                        not owner_verified and p.returncode == 37 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "nx_bypass_executed":
            accepted = (map_verified and reservation_verified and not pte_verified and
                        nx_bypass_executed and not nx_fault_verified and not route_verified and
                        not owner_verified and p.returncode == 39 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "wp_hardware_fault":
            accepted = (map_verified and reservation_verified and not pte_verified and
                        wp_fault_verified and ist_fault_verified and not wp_bypass_executed and
                        not nx_fault_verified and not nx_bypass_executed and
                        not route_verified and not owner_verified and p.returncode == 41 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "wp_bypass_stored":
            accepted = (map_verified and reservation_verified and not pte_verified and
                        wp_bypass_executed and not wp_fault_verified and
                        not nx_fault_verified and not nx_bypass_executed and
                        not route_verified and not owner_verified and p.returncode == 43 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "pf_record_corrupt_rejected":
            accepted = (map_verified and reservation_verified and pt_commit_verified and
                        not pf_admitted and not pte_verified and not route_verified and
                        not owner_verified and not nx_fault_verified and
                        p.returncode == 35 and FAIL_MARKER in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pt_commit_conflict_rejected":
            accepted = (map_verified and reservation_verified and not pt_commit_verified and
                        not pte_verified and not route_verified and not owner_verified and
                        p.returncode == 35 and FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "pte_unsafe_rejected":
            accepted = (map_verified and reservation_verified and not pte_verified and
                        not route_verified and not owner_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode in ("reserved_rejected", "nonvolatile_rejected"):
            # Real HIA E820 must reject both enabled type-2 reservations
            # and enabled type-1 nonvolatile ranges before any RAM probe.
            accepted = (not map_verified and not reservation_verified and not pte_verified and not route_verified and not owner_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "protected_rejected":
            accepted = (map_verified and not reservation_verified and not pte_verified and not route_verified and
                        not owner_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "unsafe_protected_bypass":
            accepted = (map_verified and reservation_verified and pte_verified and route_verified and owner_verified and
                        p.returncode == 33 and p.stdout.count(PASS_MARKER) == 1 and
                        FAIL_MARKER not in p.stdout)
        elif mode in ("unsafe_map_bypass", "unsafe_nonvolatile_bypass"):
            # Deliberately dishonest HIA E820 object falsely accepts the
            # identical injected reservation. This is a negative control.
            accepted = (map_verified and reservation_verified and pte_verified and route_verified and owner_verified and p.returncode == 33 and
                        p.stdout.count(PASS_MARKER) == 1 and FAIL_MARKER not in p.stdout)
        else:
            raise ValueError("unknown boot mode " + mode)
        # An independent marker is mandatory on every execution that reaches
        # the native HIA table commit, including faults and dishonest controls.
        precommit = {"reserved_rejected", "nonvolatile_rejected", "protected_rejected",
                     "pte_unsafe_rejected", "pt_commit_conflict_rejected"}
        accepted = accepted and (pt_commit_verified == (mode not in precommit | {"idt_conflict_rejected", "tss_gdt_conflict_rejected", "tss_state_conflict_rejected"}))
        accepted = accepted and (state_verified == (mode != "tss_state_conflict_rejected"))
        accepted = accepted and (state_stale == (mode == "tss_state_conflict_rejected"))
        accepted = accepted and (tss_verified == (mode not in {"tss_gdt_conflict_rejected", "tss_state_conflict_rejected"}))
        accepted = accepted and (tss_stale == (mode == "tss_gdt_conflict_rejected"))
        accepted = accepted and (idt_verified == (mode not in {"idt_conflict_rejected","tss_gdt_conflict_rejected","tss_state_conflict_rejected"}))
        accepted = accepted and (idt_stale_rejected == (mode == "idt_conflict_rejected"))
        accepted = accepted and (pf_admitted == (mode in {"nx_hardware_fault", "wp_hardware_fault"}))
        record["status"] = "PASS" if accepted else "FAIL"
    except subprocess.TimeoutExpired as e:
        record.update(status="FAIL", error="QEMU timed out", stdout=str(e.stdout), stderr=str(e.stderr))
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qemu", default="qemu-system-x86_64")
    ap.add_argument("--report", type=Path, default=Path("build/boot-report.json"))
    args = ap.parse_args()
    report = {"schema": "heptakernel.boot-tests.v1", "scope": "x86-64 TCG foundation",
              "hardware_qualification": False, "linux_compatibility": False,
              "all_kernel_code_in_hia": False,
              "source_sha256": digest("src/kernel.hepta"), "hia_object_sha256": digest("build/kernel.o"),
              "bridge_sha256": digest("arch/x86_64/boot.S"),
              "native_hia_tss_state_object_sha256": digest("build/x86-tss-state.o"),
               "native_hia_tss_state_boot_sha256": digest("build/tss-state-boot.o"),
               "tss_state_conflict_boot_sha256": digest("build/boot-tss-state-conflict.o"),
               "native_hia_tss_gdt_object_sha256": digest("build/x86-tss-gdt.o"),
              "native_hia_tss_gdt_boot_symbol_sha256": digest("build/tss-gdt-boot.o"),
              "tss_gdt_conflict_boot_object_sha256": digest("build/boot-tss-conflict.o"),
              "native_hia_idt_gate_object_sha256": digest("build/x86-idt.o"),
              "native_hia_idt_boot_symbol_object_sha256": digest("build/idt-gate-boot.o"),
              "idt_conflict_boot_object_sha256": digest("build/boot-idt-conflict.o"),
              "native_hia_e820_object_sha256": digest("build/e820-region.o"),
              "native_hia_arena_router_object_sha256": digest("build/arena-router.o"),
              "native_hia_reservation_object_sha256": digest("build/reservation-gate.o"),
              "native_hia_pte_object_sha256": digest("build/x86-pte.o"),
              "native_hia_pt_commit_object_sha256": digest("build/x86-pt-commit.o"),
              "native_hia_pf_gate_object_sha256": digest("build/x86-pf-gate.o"),
              "pf_record_corrupt_boot_object_sha256": digest("build/boot-pf-corrupt.o"),
              "pt_commit_conflict_boot_object_sha256": digest("build/boot-pt-commit-conflict.o"),
              "dishonest_hia_reservation_object_sha256": digest("build/reservation-unsafe-boot.o"),
              "dishonest_hia_e820_object_sha256": digest("build/e820-allow-all.o"),
              "dishonest_hia_router_object_sha256": digest("build/arena-unsafe-boot.o"),
              "reserved_boot_object_sha256": digest("build/boot-reserved.o"),
              "owner_alias_boot_object_sha256": digest("build/boot-owner-alias.o"),
              "nx_fault_boot_object_sha256": digest("build/boot-nx-fault.o"),
              "nx_bypass_boot_object_sha256": digest("build/boot-nx-bypass.o"),
               "wp_fault_boot_object_sha256": digest("build/boot-wp-fault.o"),
               "wp_bypass_boot_object_sha256": digest("build/boot-wp-bypass.o"),
              "protected_conflict_boot_object_sha256": digest("build/boot-reservation-conflict.o"),
              "fixtures_sha256": digest("tests/boot-cases.json"), "runs": []}
    try:
        version = subprocess.run([args.qemu, "--version"], capture_output=True, text=True, timeout=10, check=True)
        report["qemu_version"] = version.stdout.splitlines()[0]
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/kernel-multiboot.elf"), machine, memory))
            report["runs"].append(run(args.qemu, Path("build/tss-state-conflict-multiboot.elf"),
                                      machine, memory, mode="tss_state_conflict_rejected"))
            report["runs"].append(run(args.qemu, Path("build/tss-conflict-multiboot.elf"),
                                      machine, memory, mode="tss_gdt_conflict_rejected"))
            report["runs"].append(run(args.qemu, Path("build/idt-conflict-multiboot.elf"),
                                      machine, memory, mode="idt_conflict_rejected"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/nx-fault-multiboot.elf"),
                                      machine, memory, mode="nx_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/nx-bypass-multiboot.elf"),
                                      machine, memory, mode="nx_bypass_executed"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/wp-fault-multiboot.elf"),
                                      machine, memory, mode="wp_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/wp-bypass-multiboot.elf"),
                                      machine, memory, mode="wp_bypass_stored"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pf-corrupt-multiboot.elf"),
                                      machine, memory, mode="pf_record_corrupt_rejected"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pt-commit-conflict-multiboot.elf"),
                                      machine, memory, mode="pt_commit_conflict_rejected"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pte-unsafe-multiboot.elf"),
                                      machine, memory, mode="pte_unsafe_rejected"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/reservation-conflict-multiboot.elf"),
                                      machine, memory, mode="protected_rejected"))
        report["runs"].append(run(args.qemu, Path("build/reservation-bypass-multiboot.elf"),
                                  mode="unsafe_protected_bypass"))
        report["runs"].append(run(args.qemu, Path("build/arena-bypass-multiboot.elf"),
                                  mode="arena_router_negative"))
        report["runs"].append(run(args.qemu, Path("build/owner-alias-multiboot.elf"),
                                  mode="owner_alias_negative"))
        for name in ("success_stub", "bounds_trap"):
            report["runs"].append(run(args.qemu, Path("build/" + name + "-multiboot.elf"),
                                      mode="allocator_negative"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/e820-reserved-multiboot.elf"),
                                      machine, memory, mode="reserved_rejected"))
        report["runs"].append(run(args.qemu, Path("build/e820-bypass-multiboot.elf"),
                                  mode="unsafe_map_bypass"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/e820-persistent-multiboot.elf"),
                                      machine, memory, mode="nonvolatile_rejected"))
        report["runs"].append(run(args.qemu, Path("build/e820-persistent-bypass-multiboot.elf"),
                                  mode="unsafe_nonvolatile_bypass"))
        report["status"] = "PASS" if all(r["status"] == "PASS" for r in report["runs"]) else "FAIL"
    except Exception as exc:
        report.update(status="FAIL", error=repr(exc))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
