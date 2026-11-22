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
TSS_RSP0_STALE_MARKER = "HEPTAKERNEL HIA TSS RSP0 STALE WORD REJECTED"
RSP0_RING3_MARKER = "HEPTAKERNEL HIA TSS RSP0 CPL3 HARDWARE SWITCH VERIFIED"
SYSRET_GDT_MARKER = "HEPTAKERNEL HIA SYSRETQ GDT SLOT INSTALLED"
SYSRET_STALE_MARKER = "HEPTAKERNEL HIA SYSRETQ GDT STALE WORD REJECTED"
SYSRET_RING3_MARKER = "HEPTAKERNEL HIA SYSRETQ CPL3 HARDWARE SWITCH VERIFIED"
SYSRET_RFLAGS_BIT3_MARKER = "HEPTAKERNEL HIA SYSRETQ RESERVED RFLAGS BIT3 REJECTED"
SYSCALL_MSR_PASS_MARKER = "HEPTAKERNEL HIA LIVE SYSCALL MSR SNAPSHOT ADMITTED"
SYSCALL_MSR_STALE_MARKER = "HEPTAKERNEL HIA SYSCALL MSR STALE SNAPSHOT REJECTED"
SYSCALL_HW_MARKER = "HEPTAKERNEL NON-HIA SYSCALL SYSRETQ HARDWARE ROUNDTRIP VERIFIED"
SYSCALL_GETPID_MARKER = "HEPTAKERNEL HIA ONE-TASK GETPID HARDWARE RESULT VERIFIED"
SYSCALL_ENOSYS_MARKER = "HEPTAKERNEL HIA ONE-TASK ENOSYS HARDWARE RESULT VERIFIED"
TASK_VIEW_TID_MARKER = "HEPTAKERNEL HIA TASK VIEW WORKER TID HARDWARE RESULT VERIFIED"
TASK_VIEW_STALE_MARKER = "HEPTAKERNEL HIA TASK VIEW MISSING LEADER REJECTED IN USER RAX"
TASK_LIFE_MARKERS = {
    "syscall_task_life_spawn_hardware": "HEPTAKERNEL HIA TASK LIFECYCLE SPAWN USER GETTID VERIFIED",
    "syscall_task_life_retire_hardware": "HEPTAKERNEL HIA TASK LIFECYCLE RETIRE USER ESRCH VERIFIED",
    "syscall_task_life_stale_hardware": "HEPTAKERNEL HIA TASK LIFECYCLE STALE RETIRE PRESERVED USER TID",
}
TASK_VIEW_MODES = {"syscall_task_view_tid_hardware", "syscall_task_view_leader_stale"} | set(TASK_LIFE_MARKERS)
SYSCALL_STACK_PASS_MARKER = "HEPTAKERNEL HIA SYSCALL KERNEL STACK ADMITTED"
SYSCALL_STACK_STALE_MARKER = "HEPTAKERNEL HIA SYSCALL KERNEL STACK STALE REJECTED"
SYSCALL_STACK_CORRUPT_MARKER = "HEPTAKERNEL SYSCALL USER STACK CORRUPTION DETECTED"
SYSCALL_FRAME_PASS_MARKER = "HEPTAKERNEL HIA SYSCALL RETURN FRAME ADMITTED"
SYSCALL_FRAME_RCX_MARKER = "HEPTAKERNEL HIA SYSCALL RETURN RCX STALE REJECTED"
SYSCALL_FRAME_R11_MARKER = "HEPTAKERNEL HIA SYSCALL RETURN R11 STALE REJECTED"
SYSCALL_FRAME_RSP_MARKER = "HEPTAKERNEL HIA SYSCALL RETURN RSP STALE REJECTED"
RSP0_DECOY_MARKER = "HEPTAKERNEL HIA TSS RSP0 DECOY STACK DETECTED"
UPPER_USER_MARKER = "HEPTAKERNEL HIA LIVE UPPER USER TABLE VERIFIED"
UPPER_USER_STALE_MARKER = "HEPTAKERNEL HIA UPPER USER TABLE STALE OLD REJECTED"
PDPT_1G_HW_MARKER = "HEPTAKERNEL HIA 1G PDPTE HARDWARE ALIAS VERIFIED"
PDPT_1G_STALE_MARKER = "HEPTAKERNEL HIA 1G PDPTE STALE OLD REJECTED"
PDPT_1G_DECOY_MARKER = "HEPTAKERNEL HIA 1G PDPTE POSTWRITE DECOY DETECTED"
PDPT_1G_WARMED_MARKER = "HEPTAKERNEL HIA 1G PDPTE HARDWARE ALIAS WARMED BEFORE UNMAP"
PDPT_1G_UNMAP_FAULT_MARKER = "HEPTAKERNEL HIA 1G PDPTE REMOVAL HARDWARE FAULT VERIFIED"
PDPT_1G_UNMAP_STALE_MARKER = "HEPTAKERNEL HIA 1G PDPTE REMOVAL STALE OLD REJECTED"
PDPT_1G_UNMAP_BYPASS_MARKER = "HEPTAKERNEL HIA 1G PDPTE REMOVAL BYPASS EXECUTED"
PDE_2M_UNMAP_WARMED_MARKER = "HEPTAKERNEL HIA 2M PDE HARDWARE LEAF WARMED BEFORE UNMAP"
PDE_2M_UNMAP_FAULT_MARKER = "HEPTAKERNEL HIA 2M PDE REMOVAL HARDWARE FAULT VERIFIED"
PDE_2M_UNMAP_STALE_MARKER = "HEPTAKERNEL HIA 2M PDE REMOVAL STALE OLD REJECTED"
PDE_2M_UNMAP_BYPASS_MARKER = "HEPTAKERNEL HIA 2M PDE REMOVAL BYPASS EXECUTED"
PDE_2M_MARKER = "HEPTAKERNEL HIA LIVE USER 2M PDE VERIFIED"
PDE_2M_STALE_MARKER = "HEPTAKERNEL HIA USER 2M PDE STALE OLD REJECTED"
USER_GDT_MARKER = "HEPTAKERNEL HIA LIVE USER GDT VERIFIED"
USER_GDT_STALE_MARKER = "HEPTAKERNEL HIA USER GDT STALE WORD REJECTED"
TSS_MARKER = "HEPTAKERNEL HIA LIVE TSS GDT VERIFIED"
TSS_STALE_MARKER = "HEPTAKERNEL HIA TSS GDT STALE WORD REJECTED"
IDT_STALE_MARKER = "HEPTAKERNEL HIA IDT STALE WORD REJECTED"
IST_MARKER = "HEPTAKERNEL HIA IDT IST1 HARDWARE STACK VERIFIED"
RESERVATION_MARKER = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
ROUTER_MARKER = "HEPTAKERNEL HIA ARENA ROUTER VERIFIED"
OWNER_MARKER = "HEPTAKERNEL HIA MULTI-ARENA OWNERSHIP VERIFIED"
PTE_MARKER = "HEPTAKERNEL HIA LIVE PTE VERIFIED"
PT_COMMIT_MARKER = "HEPTAKERNEL HIA PT COMMIT VERIFIED"
PT_NX_MARKER = "HEPTAKERNEL HIA LIVE PT NX PROTECT VERIFIED"
PT_NX_FAULT_MARKER = "HEPTAKERNEL HIA PT NX HARDWARE FETCH FAULT VERIFIED"
PT_NX_STALE_MARKER = "HEPTAKERNEL HIA PT NX STALE OLD REJECTED"
PT_NX_BYPASS_MARKER = "HEPTAKERNEL HIA PT NX BYPASS EXECUTED"
US_INITIAL_MARKER = "HEPTAKERNEL HIA CPL3 USER FETCH BEFORE REVOKE VERIFIED"
US_LIVE_MARKER = "HEPTAKERNEL HIA LIVE PT USER REVOKE VERIFIED"
US_FAULT_MARKER = "HEPTAKERNEL HIA PT USER REVOKE CPL3 FAULT VERIFIED"
US_STALE_MARKER = "HEPTAKERNEL HIA PT USER REVOKE STALE REJECTED"
US_BYPASS_MARKER = "HEPTAKERNEL HIA PT USER REVOKE BYPASS EXECUTED"
PT_PROTECT_MARKER = "HEPTAKERNEL HIA LIVE PT WRITE PROTECT VERIFIED"
PT_PROTECT_FAULT_MARKER = "HEPTAKERNEL HIA PT WRITE PROTECT HARDWARE FAULT VERIFIED"
PT_PROTECT_STALE_MARKER = "HEPTAKERNEL HIA PT WRITE PROTECT STALE OLD REJECTED"
PT_PROTECT_BYPASS_MARKER = "HEPTAKERNEL HIA PT WRITE PROTECT BYPASS STORED"
PT_REVOKE_MARKER = "HEPTAKERNEL HIA LIVE PT REVOKE VERIFIED"
PT_REVOKE_FAULT_MARKER = "HEPTAKERNEL HIA PT REVOKE HARDWARE FAULT VERIFIED"
PT_REVOKE_STALE_MARKER = "HEPTAKERNEL HIA PT REVOKE STALE OLD REJECTED"
PT_REVOKE_BYPASS_MARKER = "HEPTAKERNEL HIA PT REVOKE BYPASS READ VERIFIED"
PF_MARKER = "HEPTAKERNEL HIA PF RECORD ADMITTED"
NX_FAULT_MARKER = "HEPTAKERNEL HIA NX FETCH FAULT VERIFIED"
NX_BYPASS_MARKER = "HEPTAKERNEL HIA NX BYPASS EXECUTED"
WP_FAULT_MARKER = "HEPTAKERNEL HIA SUPERVISOR WRITE-PROTECT FAULT VERIFIED"
WP_BYPASS_MARKER = "HEPTAKERNEL HIA WRITE-PROTECT BYPASS STORED"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(qemu, image, machine="pc", memory="32", mode="positive"):
    cpu = "qemu64,+pdpe1gb" if mode.startswith("pdpt_1g_") else "qemu64"
    cmd = [qemu, "-accel", "tcg", "-machine", machine, "-cpu", cpu, "-m", memory,
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
        rsp0_stale = p.stdout.count(TSS_RSP0_STALE_MARKER) == 1
        ring3_observed = p.stdout.count(RSP0_RING3_MARKER) == 1
        sysret_gdt_observed = p.stdout.count(SYSRET_GDT_MARKER) == 1
        sysret_stale_observed = p.stdout.count(SYSRET_STALE_MARKER) == 1
        sysret_ring3_observed = p.stdout.count(SYSRET_RING3_MARKER) == 1
        sysret_bit3_observed = p.stdout.count(SYSRET_RFLAGS_BIT3_MARKER) == 1
        syscall_admit_observed = p.stdout.count(SYSCALL_MSR_PASS_MARKER) == 1
        syscall_stale_observed = p.stdout.count(SYSCALL_MSR_STALE_MARKER) == 1
        syscall_hardware_observed = p.stdout.count(SYSCALL_HW_MARKER) == 1
        syscall_getpid_observed = p.stdout.count(SYSCALL_GETPID_MARKER) == 1
        syscall_enosys_observed = p.stdout.count(SYSCALL_ENOSYS_MARKER) == 1
        task_tid_observed = p.stdout.count(TASK_VIEW_TID_MARKER) == 1
        task_stale_observed = p.stdout.count(TASK_VIEW_STALE_MARKER) == 1
        task_life_observed = {key: p.stdout.count(marker) == 1
                              for key, marker in TASK_LIFE_MARKERS.items()}
        record["hia_task_lifecycle_hardware"] = task_life_observed
        record["hia_task_view_tid_observed"] = task_tid_observed
        record["hia_task_view_stale_observed"] = task_stale_observed
        record["hia_one_task_getpid_observed"] = syscall_getpid_observed
        record["hia_one_task_enosys_observed"] = syscall_enosys_observed
        stack_pass = p.stdout.count(SYSCALL_STACK_PASS_MARKER) == 1
        stack_stale = p.stdout.count(SYSCALL_STACK_STALE_MARKER) == 1
        stack_corrupt = p.stdout.count(SYSCALL_STACK_CORRUPT_MARKER) == 1
        frame_pass = p.stdout.count(SYSCALL_FRAME_PASS_MARKER) == 1
        frame_rcx_stale = p.stdout.count(SYSCALL_FRAME_RCX_MARKER) == 1
        frame_r11_stale = p.stdout.count(SYSCALL_FRAME_R11_MARKER) == 1
        frame_rsp_stale = p.stdout.count(SYSCALL_FRAME_RSP_MARKER) == 1
        record["hia_syscall_return_frame_admitted"] = frame_pass
        record["hia_syscall_return_frame_rcx_stale"] = frame_rcx_stale
        record["hia_syscall_return_frame_r11_stale"] = frame_r11_stale
        record["hia_syscall_return_frame_rsp_stale"] = frame_rsp_stale
        record["hia_syscall_stack_admitted"] = stack_pass
        record["hia_syscall_stack_stale"] = stack_stale
        record["user_stack_corrupt"] = stack_corrupt
        record["native_hia_live_syscall_msr_admitted"] = syscall_admit_observed
        record["native_hia_syscall_msr_stale_rejected"] = syscall_stale_observed
        record["hardware_syscall_sysret_roundtrip_observed"] = syscall_hardware_observed
        record["native_hia_sysret_gdt_observed"] = sysret_gdt_observed
        record["sysret_gdt_stale_refusal_observed"] = sysret_stale_observed
        record["hardware_sysretq_cpl3_observed"] = sysret_ring3_observed
        record["native_hia_sysret_rflags_bit3_refused"] = sysret_bit3_observed
        decoy_observed = p.stdout.count(RSP0_DECOY_MARKER) == 1
        record["hardware_cpl3_rsp0_observed"] = ring3_observed
        record["mutated_rsp0_decoy_detected"] = decoy_observed
        record["native_hia_tss_state_observed"] = state_verified
        record["native_hia_tss_state_stale_observed"] = state_stale
        record["native_hia_tss_rsp0_stale_observed"] = rsp0_stale
        user_gdt_verified = p.stdout.count(USER_GDT_MARKER) == 1
        user_gdt_stale = p.stdout.count(USER_GDT_STALE_MARKER) == 1
        upper_verified = p.stdout.count(UPPER_USER_MARKER) == 1
        upper_stale = p.stdout.count(UPPER_USER_STALE_MARKER) == 1
        record["native_hia_live_upper_user_grant"] = upper_verified
        record["native_hia_upper_user_stale_rejected"] = upper_stale
        pdpt_1g_hw = p.stdout.count(PDPT_1G_HW_MARKER) == 1
        pdpt_1g_stale = p.stdout.count(PDPT_1G_STALE_MARKER) == 1
        pdpt_1g_decoy = p.stdout.count(PDPT_1G_DECOY_MARKER) == 1
        pdpt_1g_warmed = p.stdout.count(PDPT_1G_WARMED_MARKER) == 1
        pdpt_1g_unmap_fault = p.stdout.count(PDPT_1G_UNMAP_FAULT_MARKER) == 1
        pdpt_1g_unmap_stale = p.stdout.count(PDPT_1G_UNMAP_STALE_MARKER) == 1
        pdpt_1g_unmap_bypass = p.stdout.count(PDPT_1G_UNMAP_BYPASS_MARKER) == 1
        record["hardware_pdpt_1g_warmed_before_unmap"] = pdpt_1g_warmed
        record["hardware_pdpt_1g_unmap_nonpresent_fault"] = pdpt_1g_unmap_fault
        record["native_hia_pdpt_1g_unmap_stale_refused"] = pdpt_1g_unmap_stale
        record["mutated_pdpt_1g_unmap_bypass_executed"] = pdpt_1g_unmap_bypass
        record["hardware_pdpt_1g_alias_verified"] = pdpt_1g_hw
        record["native_hia_pdpt_1g_stale_refused"] = pdpt_1g_stale
        record["pdpt_1g_postwrite_decoy_detected"] = pdpt_1g_decoy
        pde_2m_warmed = p.stdout.count(PDE_2M_UNMAP_WARMED_MARKER) == 1
        pde_2m_fault = p.stdout.count(PDE_2M_UNMAP_FAULT_MARKER) == 1
        pde_2m_stale = p.stdout.count(PDE_2M_UNMAP_STALE_MARKER) == 1
        pde_2m_bypass = p.stdout.count(PDE_2M_UNMAP_BYPASS_MARKER) == 1
        record["hardware_pde_2m_warmed_before_unmap"] = pde_2m_warmed
        record["hardware_pde_2m_unmap_nonpresent_fault"] = pde_2m_fault
        record["native_hia_pde_2m_unmap_stale_refused"] = pde_2m_stale
        record["mutated_pde_2m_unmap_bypass_executed"] = pde_2m_bypass
        pde_verified = p.stdout.count(PDE_2M_MARKER) == 1
        pde_stale = p.stdout.count(PDE_2M_STALE_MARKER) == 1
        record["native_hia_live_user_huge_pde"] = pde_verified
        record["native_hia_user_huge_pde_stale_refused"] = pde_stale
        record["native_hia_user_gdt_observed"] = user_gdt_verified
        record["native_hia_user_gdt_stale_refusal_observed"] = user_gdt_stale
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
        nx_protect_verified = p.stdout.count(PT_NX_MARKER) == 1
        nx_protect_fault = p.stdout.count(PT_NX_FAULT_MARKER) == 1
        nx_protect_stale = p.stdout.count(PT_NX_STALE_MARKER) == 1
        nx_protect_bypass = p.stdout.count(PT_NX_BYPASS_MARKER) == 1
        us_initial = p.stdout.count(US_INITIAL_MARKER) == 1
        us_live = p.stdout.count(US_LIVE_MARKER) == 1
        us_fault = p.stdout.count(US_FAULT_MARKER) == 1
        us_stale = p.stdout.count(US_STALE_MARKER) == 1
        us_bypass = p.stdout.count(US_BYPASS_MARKER) == 1
        record["hardware_cpl3_user_fetch_before_revoke"] = us_initial
        record["native_hia_user_revoke_live"] = us_live
        record["hardware_cpl3_fault_after_user_revoke"] = us_fault
        record["native_hia_user_revoke_stale_rejected"] = us_stale
        record["mutated_user_revoke_bypass_executed"] = us_bypass
        record["native_hia_pt_nx_observed"] = nx_protect_verified
        record["hardware_nx_fault_after_hia_downgrade"] = nx_protect_fault
        record["native_hia_pt_nx_stale_refused"] = nx_protect_stale
        record["mutated_pt_nx_bypass_executed"] = nx_protect_bypass
        protect_verified = p.stdout.count(PT_PROTECT_MARKER) == 1
        protect_fault = p.stdout.count(PT_PROTECT_FAULT_MARKER) == 1
        protect_stale = p.stdout.count(PT_PROTECT_STALE_MARKER) == 1
        protect_bypass = p.stdout.count(PT_PROTECT_BYPASS_MARKER) == 1
        record["native_hia_pt_protect_observed"] = protect_verified
        record["hardware_write_fault_after_hia_downgrade"] = protect_fault
        record["native_hia_pt_protect_stale_refused"] = protect_stale
        record["mutated_pt_protect_bypass_stored"] = protect_bypass
        revoke_verified = p.stdout.count(PT_REVOKE_MARKER) == 1
        revoke_fault = p.stdout.count(PT_REVOKE_FAULT_MARKER) == 1
        revoke_stale = p.stdout.count(PT_REVOKE_STALE_MARKER) == 1
        revoke_bypass = p.stdout.count(PT_REVOKE_BYPASS_MARKER) == 1
        record["native_hia_pt_revoke_observed"] = revoke_verified
        record["hardware_not_present_after_hia_revoke"] = revoke_fault
        record["native_hia_pt_revoke_stale_refused"] = revoke_stale
        record["mutated_pt_revoke_bypass_readback"] = revoke_bypass
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
        if mode == "pde_2m_unmap_hardware_fault":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pde_2m_warmed and pde_2m_fault and
                        ist_fault_verified and not pde_2m_stale and not pde_2m_bypass and
                        not pte_verified and not route_verified and
                        p.returncode == 91 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pde_2m_unmap_stale":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pde_2m_warmed and pde_2m_stale and
                        not pde_2m_fault and not pde_2m_bypass and not ist_fault_verified and
                        not pte_verified and not route_verified and
                        p.returncode == 93 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pde_2m_unmap_bypass":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pde_2m_warmed and pde_2m_bypass and
                        not pde_2m_fault and not pde_2m_stale and not ist_fault_verified and
                        not pte_verified and not route_verified and
                        p.returncode == 95 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pdpt_1g_hardware":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pdpt_1g_hw and
                        not pdpt_1g_stale and not pdpt_1g_decoy and
                        not pte_verified and not route_verified and
                        p.returncode == 81 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pdpt_1g_stale":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pdpt_1g_stale and
                        not pdpt_1g_hw and not pdpt_1g_decoy and
                        not pte_verified and not route_verified and
                        p.returncode == 83 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pdpt_1g_decoy":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pdpt_1g_decoy and
                        not pdpt_1g_stale and not pdpt_1g_hw and
                        not pte_verified and not route_verified and
                        p.returncode == 35 and FAIL_MARKER in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pdpt_1g_unmap_hardware_fault":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pdpt_1g_warmed and
                        pdpt_1g_unmap_fault and ist_fault_verified and
                        not pdpt_1g_unmap_stale and not pdpt_1g_unmap_bypass and
                        not pdpt_1g_hw and not pdpt_1g_stale and not pdpt_1g_decoy and
                        not pte_verified and not route_verified and
                        p.returncode == 85 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pdpt_1g_unmap_stale":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pdpt_1g_warmed and
                        pdpt_1g_unmap_stale and not pdpt_1g_unmap_fault and
                        not pdpt_1g_unmap_bypass and not ist_fault_verified and
                        not pdpt_1g_hw and not pdpt_1g_stale and not pdpt_1g_decoy and
                        not pte_verified and not route_verified and
                        p.returncode == 87 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pdpt_1g_unmap_bypass":
            accepted = (state_verified and idt_verified and map_verified and
                        reservation_verified and pdpt_1g_warmed and
                        pdpt_1g_unmap_bypass and not pdpt_1g_unmap_fault and
                        not pdpt_1g_unmap_stale and not ist_fault_verified and
                        not pdpt_1g_hw and not pdpt_1g_stale and not pdpt_1g_decoy and
                        not pte_verified and not route_verified and
                        p.returncode == 89 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "user_gdt_conflict_rejected":
            accepted = (state_verified and user_gdt_stale and not user_gdt_verified
                        and not tss_verified and not idt_verified and not map_verified
                        and p.returncode == 35 and FAIL_MARKER in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode == "upper_user_stale_rejected":
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and upper_stale and not upper_verified and not pde_verified
                        and not ring3_observed and not decoy_observed
                        and not pte_verified and not route_verified
                        and p.returncode == 35 and PASS_MARKER not in p.stdout
                        and FAIL_MARKER in p.stdout)
        elif mode == "pde_2m_stale_rejected":
            accepted = (state_verified and user_gdt_verified and tss_verified and
                        idt_verified and map_verified and reservation_verified and
                        pde_stale and not pde_verified and not ring3_observed and
                        not decoy_observed and not pte_verified and
                        not route_verified and p.returncode == 35 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER in p.stdout)
        elif mode == "us_revoke_hardware_fault":
            accepted = (state_verified and user_gdt_verified and tss_verified and
                        idt_verified and map_verified and reservation_verified and
                        upper_verified and pde_verified and pt_commit_verified and
                        us_initial and us_live and us_fault and ist_fault_verified and
                        not us_stale and not us_bypass and not ring3_observed and
                        not pte_verified and p.returncode == 67 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "us_revoke_stale_rejected":
            accepted = (state_verified and user_gdt_verified and tss_verified and
                        idt_verified and map_verified and reservation_verified and
                        upper_verified and pde_verified and pt_commit_verified and
                        us_initial and us_stale and not us_live and not us_fault and
                        not us_bypass and not ist_fault_verified and not ring3_observed and
                        not pte_verified and p.returncode == 73 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "us_revoke_bypass_executed":
            accepted = (state_verified and user_gdt_verified and tss_verified and
                        idt_verified and map_verified and reservation_verified and
                        upper_verified and pde_verified and pt_commit_verified and
                        us_initial and us_live and us_bypass and not us_fault and
                        not us_stale and not ist_fault_verified and not ring3_observed and
                        not pte_verified and p.returncode == 69 and
                        PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode in ("syscall_roundtrip_hardware",
                       "syscall_one_task_getpid_hardware", "syscall_one_task_enosys_hardware") or mode in TASK_VIEW_MODES:
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and sysret_gdt_observed and syscall_admit_observed
                        and syscall_hardware_observed == (mode == "syscall_roundtrip_hardware")
                        and syscall_getpid_observed == (mode == "syscall_one_task_getpid_hardware")
                        and syscall_enosys_observed == (mode == "syscall_one_task_enosys_hardware")
                        and task_tid_observed == (mode == "syscall_task_view_tid_hardware")
                        and task_stale_observed == (mode == "syscall_task_view_leader_stale")
                        and all(observed == (mode == name)
                                for name, observed in task_life_observed.items())
                        and stack_pass and frame_pass
                        and not frame_rcx_stale and not frame_r11_stale and not frame_rsp_stale
                        and not stack_stale and not stack_corrupt and not syscall_stale_observed
                        and not sysret_ring3_observed and not ring3_observed
                        and not pte_verified and not route_verified
                        and p.returncode == 45 and FAIL_MARKER not in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode == "syscall_msr_stale_rejected":
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and sysret_gdt_observed and syscall_stale_observed
                        and not syscall_admit_observed and not syscall_hardware_observed
                        and not sysret_ring3_observed and not ring3_observed
                        and not pte_verified and not route_verified
                        and p.returncode == 35 and FAIL_MARKER in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode in ("syscall_stack_stale_rejected", "syscall_stack_corrupt_rejected"):
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and sysret_gdt_observed and syscall_admit_observed
                        and stack_stale == (mode == "syscall_stack_stale_rejected")
                        and stack_corrupt == (mode == "syscall_stack_corrupt_rejected")
                        and not stack_pass and not syscall_stale_observed
                        and not syscall_hardware_observed and not ring3_observed
                        and not pte_verified and not route_verified
                        and p.returncode == 35 and FAIL_MARKER in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode in ("syscall_frame_rcx_stale_rejected", "syscall_frame_r11_stale_rejected",
                      "syscall_frame_rsp_stale_rejected"):
            expected = ("syscall_frame_rcx_stale_rejected",
                        "syscall_frame_r11_stale_rejected",
                        "syscall_frame_rsp_stale_rejected")
            observations = (frame_rcx_stale, frame_r11_stale, frame_rsp_stale)
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and sysret_gdt_observed and syscall_admit_observed and stack_pass
                        and observations == tuple(mode == m for m in expected)
                        and not frame_pass and not stack_stale and not stack_corrupt
                        and not syscall_hardware_observed and not syscall_stale_observed
                        and not sysret_ring3_observed and not ring3_observed
                        and not pte_verified and not route_verified
                        and p.returncode == 35 and FAIL_MARKER in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode == "sysret_ring3_hardware":
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and sysret_gdt_observed and sysret_ring3_observed
                        and not sysret_stale_observed and not ring3_observed
                        and not decoy_observed and not pte_verified
                        and not route_verified and p.returncode == 45
                        and PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "sysret_rflags_bit3_rejected":
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and sysret_gdt_observed and sysret_bit3_observed
                        and not sysret_ring3_observed and not sysret_stale_observed
                        and not syscall_admit_observed and not syscall_hardware_observed
                        and not ring3_observed and not pte_verified and not route_verified
                        and p.returncode == 35 and FAIL_MARKER in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode == "sysret_gdt_stale_rejected":
            accepted = (state_verified and user_gdt_verified and tss_verified
                        and idt_verified and map_verified and reservation_verified
                        and sysret_stale_observed and not sysret_gdt_observed
                        and not sysret_ring3_observed and not ring3_observed
                        and not pte_verified and not route_verified and p.returncode == 35
                        and PASS_MARKER not in p.stdout and FAIL_MARKER in p.stdout)
        elif mode == "rsp0_ring3_hardware":
            accepted = (state_verified and tss_verified and idt_verified
                        and map_verified and reservation_verified and ring3_observed
                        and not decoy_observed and not pte_verified
                        and not route_verified and p.returncode == 45
                        and PASS_MARKER not in p.stdout and FAIL_MARKER not in p.stdout)
        elif mode == "rsp0_decoy_rejected":
            accepted = (state_verified and tss_verified and idt_verified
                        and map_verified and reservation_verified and decoy_observed
                        and not ring3_observed and not pte_verified
                        and not route_verified and p.returncode == 35
                        and PASS_MARKER not in p.stdout and FAIL_MARKER in p.stdout)
        elif mode == "tss_state_conflict_rejected":
            accepted = (state_stale and not state_verified and not tss_verified and
                        not idt_verified and not map_verified and p.returncode == 35 and
                        FAIL_MARKER in p.stdout and PASS_MARKER not in p.stdout)
        elif mode == "tss_rsp0_conflict_rejected":
            accepted = (rsp0_stale and not state_stale and not state_verified
                        and not tss_verified and not idt_verified and not map_verified
                        and p.returncode == 35 and FAIL_MARKER in p.stdout
                        and PASS_MARKER not in p.stdout)
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
        elif mode == "pt_nx_hardware_fault":
            accepted = (map_verified and reservation_verified and pt_commit_verified and
                        nx_protect_verified and nx_protect_fault and ist_fault_verified and
                        not nx_protect_stale and not nx_protect_bypass and
                        not pte_verified and not route_verified and not owner_verified and
                        p.returncode == 59 and PASS_MARKER not in p.stdout and
                        FAIL_MARKER not in p.stdout)
        elif mode == "pt_nx_stale_rejected":
            accepted = (map_verified and reservation_verified and pt_commit_verified and
                        nx_protect_stale and not nx_protect_verified and not nx_protect_fault and
                        not nx_protect_bypass and not pte_verified and not route_verified and
                        p.returncode == 35 and FAIL_MARKER in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pt_nx_bypass_executed":
            accepted = (map_verified and reservation_verified and pt_commit_verified and
                        nx_protect_verified and nx_protect_bypass and not nx_protect_fault and
                        not nx_protect_stale and not pte_verified and not route_verified and
                        p.returncode == 61 and FAIL_MARKER not in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pt_protect_hardware_fault":
            accepted = (map_verified and reservation_verified and pt_commit_verified
                        and protect_verified and protect_fault and ist_fault_verified
                        and not protect_stale and not protect_bypass and
                        not pte_verified and not route_verified and not owner_verified
                        and p.returncode == 55 and PASS_MARKER not in p.stdout
                        and FAIL_MARKER not in p.stdout)
        elif mode == "pt_protect_stale_rejected":
            accepted = (map_verified and reservation_verified and pt_commit_verified
                        and protect_stale and not protect_verified and not protect_fault
                        and not protect_bypass and not pte_verified and not route_verified
                        and p.returncode == 35 and FAIL_MARKER in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode == "pt_protect_bypass_stored":
            accepted = (map_verified and reservation_verified and pt_commit_verified
                        and protect_verified and protect_bypass and not protect_fault
                        and not protect_stale and not pte_verified and not route_verified
                        and p.returncode == 57 and FAIL_MARKER not in p.stdout
                        and PASS_MARKER not in p.stdout)
        elif mode == "pt_revoke_hardware_fault":
            accepted = (map_verified and reservation_verified and pt_commit_verified and
                        revoke_verified and revoke_fault and ist_fault_verified and
                        not revoke_stale and not revoke_bypass and
                        not pte_verified and not route_verified and not owner_verified and
                        p.returncode == 51 and PASS_MARKER not in p.stdout and
                        FAIL_MARKER not in p.stdout)
        elif mode == "pt_revoke_stale_rejected":
            accepted = (map_verified and reservation_verified and pt_commit_verified and
                        revoke_stale and not revoke_verified and not revoke_fault and
                        not revoke_bypass and not pte_verified and not route_verified and
                        p.returncode == 35 and FAIL_MARKER in p.stdout and
                        PASS_MARKER not in p.stdout)
        elif mode == "pt_revoke_bypass_read":
            accepted = (map_verified and reservation_verified and pt_commit_verified and
                        revoke_verified and revoke_bypass and not revoke_fault and
                        not revoke_stale and not pte_verified and not route_verified and
                        p.returncode == 53 and FAIL_MARKER not in p.stdout and
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
        # All mode/marker combinations are explicitly partitioned.
        frame_bad_modes = {"syscall_frame_rcx_stale_rejected",
                           "syscall_frame_r11_stale_rejected",
                           "syscall_frame_rsp_stale_rejected"}
        roundtrip_modes = {"syscall_roundtrip_hardware", "syscall_one_task_getpid_hardware",
                           "syscall_one_task_enosys_hardware"} | TASK_VIEW_MODES
        frame_modes = frame_bad_modes | roundtrip_modes
        accepted = accepted and (sysret_gdt_observed == (mode in {
            "sysret_ring3_hardware", "sysret_rflags_bit3_rejected", "syscall_roundtrip_hardware",
            "syscall_one_task_getpid_hardware", "syscall_one_task_enosys_hardware",
            "syscall_msr_stale_rejected", "syscall_stack_stale_rejected",
            "syscall_stack_corrupt_rejected"} | frame_bad_modes | TASK_VIEW_MODES))
        accepted = accepted and (syscall_admit_observed == (mode in {
            "syscall_roundtrip_hardware", "syscall_one_task_getpid_hardware",
            "syscall_one_task_enosys_hardware", "syscall_stack_stale_rejected",
            "syscall_stack_corrupt_rejected"} | frame_bad_modes | TASK_VIEW_MODES))
        accepted = accepted and (syscall_stale_observed == (mode == "syscall_msr_stale_rejected"))
        accepted = accepted and (syscall_hardware_observed == (mode == "syscall_roundtrip_hardware"))
        accepted = accepted and (stack_pass == (mode in frame_modes))
        accepted = accepted and (stack_stale == (mode == "syscall_stack_stale_rejected"))
        accepted = accepted and (stack_corrupt == (mode == "syscall_stack_corrupt_rejected"))
        accepted = accepted and (frame_pass == (mode in roundtrip_modes))
        accepted = accepted and (syscall_getpid_observed == (mode == "syscall_one_task_getpid_hardware"))
        accepted = accepted and (syscall_enosys_observed == (mode == "syscall_one_task_enosys_hardware"))
        accepted = accepted and (task_tid_observed == (mode == "syscall_task_view_tid_hardware"))
        accepted = accepted and (task_stale_observed == (mode == "syscall_task_view_leader_stale"))
        accepted = accepted and all(observed == (mode == name)
                                    for name, observed in task_life_observed.items())
        accepted = accepted and (frame_rcx_stale == (mode == "syscall_frame_rcx_stale_rejected"))
        accepted = accepted and (frame_r11_stale == (mode == "syscall_frame_r11_stale_rejected"))
        accepted = accepted and (frame_rsp_stale == (mode == "syscall_frame_rsp_stale_rejected"))
        accepted = accepted and (sysret_ring3_observed == (mode == "sysret_ring3_hardware"))
        accepted = accepted and (sysret_bit3_observed == (mode == "sysret_rflags_bit3_rejected"))
        accepted = accepted and (sysret_stale_observed == (mode == "sysret_gdt_stale_rejected"))
        accepted = accepted and (pdpt_1g_hw == (mode == "pdpt_1g_hardware"))
        accepted = accepted and (pdpt_1g_stale == (mode == "pdpt_1g_stale"))
        accepted = accepted and (pdpt_1g_decoy == (mode == "pdpt_1g_decoy"))
        unmap_modes = {"pdpt_1g_unmap_hardware_fault", "pdpt_1g_unmap_stale", "pdpt_1g_unmap_bypass"}
        accepted = accepted and (pdpt_1g_warmed == (mode in unmap_modes))
        accepted = accepted and (pdpt_1g_unmap_fault == (mode == "pdpt_1g_unmap_hardware_fault"))
        accepted = accepted and (pdpt_1g_unmap_stale == (mode == "pdpt_1g_unmap_stale"))
        accepted = accepted and (pdpt_1g_unmap_bypass == (mode == "pdpt_1g_unmap_bypass"))
        accepted = accepted and (us_initial == (mode in {"us_revoke_hardware_fault", "us_revoke_stale_rejected", "us_revoke_bypass_executed"}))
        accepted = accepted and (us_live == (mode in {"us_revoke_hardware_fault", "us_revoke_bypass_executed"}))
        accepted = accepted and (us_fault == (mode == "us_revoke_hardware_fault"))
        accepted = accepted and (us_stale == (mode == "us_revoke_stale_rejected"))
        accepted = accepted and (us_bypass == (mode == "us_revoke_bypass_executed"))
        accepted = accepted and (nx_protect_verified == (mode in
                      {"pt_nx_hardware_fault", "pt_nx_bypass_executed"}))
        accepted = accepted and (nx_protect_fault == (mode == "pt_nx_hardware_fault"))
        accepted = accepted and (nx_protect_stale == (mode == "pt_nx_stale_rejected"))
        accepted = accepted and (nx_protect_bypass == (mode == "pt_nx_bypass_executed"))
        accepted = accepted and (protect_verified == (mode in
                      {"pt_protect_hardware_fault", "pt_protect_bypass_stored"}))
        accepted = accepted and (protect_fault == (mode == "pt_protect_hardware_fault"))
        accepted = accepted and (protect_stale == (mode == "pt_protect_stale_rejected"))
        accepted = accepted and (protect_bypass == (mode == "pt_protect_bypass_stored"))
        # These live-MMU markers are mutually exclusive and absent in all
        # earlier scenarios; correct exit status alone cannot make them pass.
        pde_unmap_modes = {"pde_2m_unmap_hardware_fault",
                           "pde_2m_unmap_stale", "pde_2m_unmap_bypass"}
        accepted = accepted and (pde_2m_warmed == (mode in pde_unmap_modes))
        accepted = accepted and (pde_2m_fault == (mode == "pde_2m_unmap_hardware_fault"))
        accepted = accepted and (pde_2m_stale == (mode == "pde_2m_unmap_stale"))
        accepted = accepted and (pde_2m_bypass == (mode == "pde_2m_unmap_bypass"))
        # Revoke-only markers must never appear on unrelated boot images.
        accepted = accepted and (revoke_verified == (mode in
                      {"pt_revoke_hardware_fault", "pt_revoke_bypass_read"}))
        accepted = accepted and (revoke_fault == (mode == "pt_revoke_hardware_fault"))
        accepted = accepted and (revoke_stale == (mode == "pt_revoke_stale_rejected"))
        accepted = accepted and (revoke_bypass == (mode == "pt_revoke_bypass_read"))
        # An independent marker is mandatory on every execution that reaches
        # the native HIA table commit, including faults and dishonest controls.
        precommit = {"reserved_rejected", "nonvolatile_rejected", "protected_rejected",
                     "pte_unsafe_rejected", "pt_commit_conflict_rejected",
                     "pdpt_1g_hardware", "pdpt_1g_stale", "pdpt_1g_decoy",
                     "pdpt_1g_unmap_hardware_fault", "pdpt_1g_unmap_stale", "pdpt_1g_unmap_bypass",
                     "pde_2m_unmap_hardware_fault", "pde_2m_unmap_stale", "pde_2m_unmap_bypass"}
        accepted = accepted and (pt_commit_verified == (mode not in precommit | {"user_gdt_conflict_rejected", "idt_conflict_rejected", "tss_gdt_conflict_rejected", "tss_state_conflict_rejected", "tss_rsp0_conflict_rejected", "rsp0_ring3_hardware", "rsp0_decoy_rejected", "sysret_ring3_hardware", "sysret_gdt_stale_rejected", "sysret_rflags_bit3_rejected", "syscall_roundtrip_hardware", "syscall_one_task_getpid_hardware", "syscall_one_task_enosys_hardware", "syscall_msr_stale_rejected", "syscall_stack_stale_rejected", "syscall_stack_corrupt_rejected", "pde_2m_stale_rejected", "upper_user_stale_rejected"} | frame_bad_modes | TASK_VIEW_MODES))
        accepted = accepted and (upper_verified == (mode in {"rsp0_ring3_hardware", "rsp0_decoy_rejected", "sysret_ring3_hardware", "sysret_rflags_bit3_rejected", "syscall_roundtrip_hardware", "syscall_one_task_getpid_hardware", "syscall_one_task_enosys_hardware", "syscall_msr_stale_rejected", "syscall_stack_stale_rejected", "syscall_stack_corrupt_rejected", "pde_2m_stale_rejected", "us_revoke_hardware_fault", "us_revoke_stale_rejected", "us_revoke_bypass_executed"} | frame_bad_modes | TASK_VIEW_MODES))
        accepted = accepted and (upper_stale == (mode == "upper_user_stale_rejected"))
        accepted = accepted and (pde_verified == (mode in {"rsp0_ring3_hardware", "rsp0_decoy_rejected", "sysret_ring3_hardware", "sysret_rflags_bit3_rejected", "syscall_roundtrip_hardware", "syscall_one_task_getpid_hardware", "syscall_one_task_enosys_hardware", "syscall_msr_stale_rejected", "syscall_stack_stale_rejected", "syscall_stack_corrupt_rejected", "us_revoke_hardware_fault", "us_revoke_stale_rejected", "us_revoke_bypass_executed"} | frame_bad_modes | TASK_VIEW_MODES))
        accepted = accepted and (pde_stale == (mode == "pde_2m_stale_rejected"))
        accepted = accepted and (state_verified == (mode not in {"tss_state_conflict_rejected", "tss_rsp0_conflict_rejected"}))
        accepted = accepted and (state_stale == (mode == "tss_state_conflict_rejected"))
        accepted = accepted and (rsp0_stale == (mode == "tss_rsp0_conflict_rejected"))
        accepted = accepted and (user_gdt_verified == (mode not in {"user_gdt_conflict_rejected", "tss_state_conflict_rejected", "tss_rsp0_conflict_rejected"}))
        accepted = accepted and (user_gdt_stale == (mode == "user_gdt_conflict_rejected"))
        accepted = accepted and (tss_verified == (mode not in {"user_gdt_conflict_rejected", "tss_gdt_conflict_rejected", "tss_state_conflict_rejected", "tss_rsp0_conflict_rejected"}))
        accepted = accepted and (tss_stale == (mode == "tss_gdt_conflict_rejected"))
        accepted = accepted and (idt_verified == (mode not in {"user_gdt_conflict_rejected", "idt_conflict_rejected","tss_gdt_conflict_rejected","tss_state_conflict_rejected","tss_rsp0_conflict_rejected"}))
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
              "native_hia_upper_user_object_sha256": digest("build/x86-upper-user.o"),
               "native_hia_upper_user_boot_sha256": digest("build/upper-user-boot.o"),
               "upper_user_stale_boot_sha256": digest("build/boot-ring3-upper-stale.o"),
               "native_hia_syscall_return_frame_object_sha256": digest("build/x86-syscall-return-frame.o"),
               "syscall_frame_rcx_stale_boot_sha256": digest("build/boot-syscall-frame-rcx-stale.o"),
               "syscall_frame_r11_stale_boot_sha256": digest("build/boot-syscall-frame-r11-stale.o"),
               "syscall_frame_rsp_stale_boot_sha256": digest("build/boot-syscall-frame-rsp-stale.o"),
               "native_hia_pde_2m_object_sha256": digest("build/x86-pde-2m.o"),
              "native_hia_pde_2m_boot_symbol_sha256": digest("build/pde-2m-boot.o"),
              "pde_2m_unmap_fault_boot_sha256": digest("build/boot-pde-2m-unmap-fault.o"),
              "pde_2m_unmap_stale_boot_sha256": digest("build/boot-pde-2m-unmap-stale.o"),
              "pde_2m_unmap_bypass_boot_sha256": digest("build/boot-pde-2m-unmap-bypass.o"),
              "pde_2m_stale_boot_sha256": digest("build/boot-ring3-pde-stale.o"),
              "native_hia_pdpt_1g_object_sha256": digest("build/x86-pdpt-1g.o"),
              "native_hia_pdpt_1g_boot_sha256": digest("build/pdpt-1g-boot.o"),
              "pdpt_1g_hardware_boot_sha256": digest("build/boot-pdpt-1g-hw.o"),
              "pdpt_1g_stale_boot_sha256": digest("build/boot-pdpt-1g-stale.o"),
              "pdpt_1g_decoy_boot_sha256": digest("build/boot-pdpt-1g-decoy.o"),
              "pdpt_1g_unmap_fault_boot_sha256": digest("build/boot-pdpt-1g-unmap-fault.o"),
              "pdpt_1g_unmap_stale_boot_sha256": digest("build/boot-pdpt-1g-unmap-stale.o"),
              "pdpt_1g_unmap_bypass_boot_sha256": digest("build/boot-pdpt-1g-unmap-bypass.o"),
              "native_hia_user_gdt_object_sha256": digest("build/x86-user-gdt.o"),
               "native_hia_user_gdt_boot_sha256": digest("build/user-gdt-boot.o"),
               "user_gdt_conflict_boot_sha256": digest("build/boot-user-gdt-conflict.o"),
               "native_hia_tss_state_object_sha256": digest("build/x86-tss-state.o"),
               "native_hia_tss_state_boot_sha256": digest("build/tss-state-boot.o"),
               "tss_state_conflict_boot_sha256": digest("build/boot-tss-state-conflict.o"),
               "tss_rsp0_conflict_boot_sha256": digest("build/boot-tss-rsp0-conflict.o"),
              "rsp0_ring3_boot_sha256": digest("build/boot-ring3-rsp0.o"),
              "rsp0_decoy_boot_sha256": digest("build/boot-ring3-rsp0-decoy.o"),
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
              "native_hia_pt_user_revoke_object_sha256": digest("build/x86-pt-user-revoke.o"),
              "native_hia_pt_user_revoke_boot_sha256": digest("build/pt-us-boot.o"),
              "us_fault_boot_sha256": digest("build/boot-us-fault.o"),
              "us_stale_boot_sha256": digest("build/boot-us-stale.o"),
              "us_bypass_boot_sha256": digest("build/boot-us-bypass.o"),
              "native_hia_pt_nx_object_sha256": digest("build/x86-pt-nx-protect.o"),
               "native_hia_pt_nx_boot_sha256": digest("build/pt-nx-boot.o"),
               "pt_nx_fault_boot_sha256": digest("build/boot-pt-nx-fault.o"),
               "pt_nx_stale_boot_sha256": digest("build/boot-pt-nx-stale.o"),
               "pt_nx_bypass_boot_sha256": digest("build/boot-pt-nx-bypass.o"),
               "native_hia_pt_protect_object_sha256": digest("build/x86-pt-write-protect.o"),
              "native_hia_pt_protect_boot_sha256": digest("build/pt-protect-boot.o"),
              "pt_protect_fault_boot_sha256": digest("build/boot-pt-protect-fault.o"),
              "pt_protect_stale_boot_sha256": digest("build/boot-pt-protect-stale.o"),
              "pt_protect_bypass_boot_sha256": digest("build/boot-pt-protect-bypass.o"),
              "native_hia_pt_revoke_object_sha256": digest("build/x86-pt-revoke.o"),
              "native_hia_pt_revoke_boot_sha256": digest("build/pt-revoke-boot.o"),
              "pt_revoke_fault_boot_sha256": digest("build/boot-pt-revoke-fault.o"),
              "pt_revoke_stale_boot_sha256": digest("build/boot-pt-revoke-stale.o"),
              "pt_revoke_bypass_boot_sha256": digest("build/boot-pt-revoke-bypass.o"),
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
            report["runs"].append(run(args.qemu, Path("build/user-gdt-conflict-multiboot.elf"),
                                       machine, memory, mode="user_gdt_conflict_rejected"))
            report["runs"].append(run(args.qemu, Path("build/tss-state-conflict-multiboot.elf"),
                                      machine, memory, mode="tss_state_conflict_rejected"))
            report["runs"].append(run(args.qemu, Path("build/tss-rsp0-conflict-multiboot.elf"),
                                       machine, memory, mode="tss_rsp0_conflict_rejected"))
            report["runs"].append(run(args.qemu, Path("build/tss-conflict-multiboot.elf"),
                                      machine, memory, mode="tss_gdt_conflict_rejected"))
            report["runs"].append(run(args.qemu, Path("build/idt-conflict-multiboot.elf"),
                                      machine, memory, mode="idt_conflict_rejected"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pde-2m-unmap-fault-multiboot.elf"),
                                      machine, memory, mode="pde_2m_unmap_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/pde-2m-unmap-stale-multiboot.elf"),
                                      machine, memory, mode="pde_2m_unmap_stale"))
            report["runs"].append(run(args.qemu, Path("build/pde-2m-unmap-bypass-multiboot.elf"),
                                      machine, memory, mode="pde_2m_unmap_bypass"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pdpt-1g-hw-multiboot.elf"),
                                      machine, memory, mode="pdpt_1g_hardware"))
            report["runs"].append(run(args.qemu, Path("build/pdpt-1g-stale-multiboot.elf"),
                                      machine, memory, mode="pdpt_1g_stale"))
            report["runs"].append(run(args.qemu, Path("build/pdpt-1g-decoy-multiboot.elf"),
                                      machine, memory, mode="pdpt_1g_decoy"))
            report["runs"].append(run(args.qemu, Path("build/pdpt-1g-unmap-fault-multiboot.elf"),
                                      machine, memory, mode="pdpt_1g_unmap_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/pdpt-1g-unmap-stale-multiboot.elf"),
                                      machine, memory, mode="pdpt_1g_unmap_stale"))
            report["runs"].append(run(args.qemu, Path("build/pdpt-1g-unmap-bypass-multiboot.elf"),
                                      machine, memory, mode="pdpt_1g_unmap_bypass"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/ring3-upper-stale-multiboot.elf"),
                                       machine, memory, mode="upper_user_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/ring3-pde-stale-multiboot.elf"),
                                      machine, memory, mode="pde_2m_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/ring3-rsp0-multiboot.elf"),
                                      machine, memory, mode="rsp0_ring3_hardware"))
            report["runs"].append(run(args.qemu, Path("build/sysret-ring3-multiboot.elf"),
                                      machine, memory, mode="sysret_ring3_hardware"))
            report["runs"].append(run(args.qemu, Path("build/sysret-rflags-bit3-multiboot.elf"),
                                      machine, memory, mode="sysret_rflags_bit3_rejected"))
            report["runs"].append(run(args.qemu, Path("build/sysret-gdt-stale-multiboot.elf"),
                                      machine, memory, mode="sysret_gdt_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/syscall-roundtrip-multiboot.elf"),
                                      machine, memory, mode="syscall_roundtrip_hardware"))
            report["runs"].append(run(args.qemu, Path("build/syscall-one-task-getpid-multiboot.elf"),
                                      machine, memory, mode="syscall_one_task_getpid_hardware"))
            report["runs"].append(run(args.qemu, Path("build/syscall-one-task-enosys-multiboot.elf"),
                                      machine, memory, mode="syscall_one_task_enosys_hardware"))
            report["runs"].append(run(args.qemu, Path("build/syscall-task-view-tid-multiboot.elf"),
                                      machine, memory, mode="syscall_task_view_tid_hardware"))
            report["runs"].append(run(args.qemu, Path("build/syscall-task-view-stale-multiboot.elf"),
                                      machine, memory, mode="syscall_task_view_leader_stale"))
            for case in ("spawn", "retire", "stale"):
                report["runs"].append(run(
                    args.qemu, Path("build/syscall-task-life-" + case + "-multiboot.elf"),
                    machine, memory, mode="syscall_task_life_" + case + "_hardware"))
            report["runs"].append(run(args.qemu, Path("build/syscall-msr-stale-multiboot.elf"),
                                      machine, memory, mode="syscall_msr_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/syscall-stack-stale-multiboot.elf"),
                                       machine, memory, mode="syscall_stack_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/syscall-stack-bypass-multiboot.elf"),
                                       machine, memory, mode="syscall_stack_corrupt_rejected"))
            for field in ("rcx", "r11", "rsp"):
                report["runs"].append(run(
                    args.qemu, Path("build/syscall-frame-" + field + "-stale-multiboot.elf"),
                    machine, memory, mode="syscall_frame_" + field + "_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/ring3-rsp0-decoy-multiboot.elf"),
                                      machine, memory, mode="rsp0_decoy_rejected"))
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
            report["runs"].append(run(args.qemu, Path("build/us-fault-multiboot.elf"),
                                      machine, memory, mode="us_revoke_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/us-stale-multiboot.elf"),
                                      machine, memory, mode="us_revoke_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/us-bypass-multiboot.elf"),
                                      machine, memory, mode="us_revoke_bypass_executed"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pt-nx-fault-multiboot.elf"),
                                       machine, memory, mode="pt_nx_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/pt-nx-stale-multiboot.elf"),
                                       machine, memory, mode="pt_nx_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/pt-nx-bypass-multiboot.elf"),
                                       machine, memory, mode="pt_nx_bypass_executed"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pt-protect-fault-multiboot.elf"),
                                      machine, memory, mode="pt_protect_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/pt-protect-stale-multiboot.elf"),
                                      machine, memory, mode="pt_protect_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/pt-protect-bypass-multiboot.elf"),
                                      machine, memory, mode="pt_protect_bypass_stored"))
        for machine, memory in (("pc", "32"), ("q35", "64")):
            report["runs"].append(run(args.qemu, Path("build/pt-revoke-fault-multiboot.elf"),
                                      machine, memory, mode="pt_revoke_hardware_fault"))
            report["runs"].append(run(args.qemu, Path("build/pt-revoke-stale-multiboot.elf"),
                                      machine, memory, mode="pt_revoke_stale_rejected"))
            report["runs"].append(run(args.qemu, Path("build/pt-revoke-bypass-multiboot.elf"),
                                      machine, memory, mode="pt_revoke_bypass_read"))
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
