# Experimental two-CPU directed xAPIC IPI

The exact #952 experimental compiler is rebuilt independently. This branch descends from the independently tested #178 subject; the original self-IPI tests are retained.

The new HIA f0 accepts only a fixed supervisor UC xAPIC aperture, live expected IA32_APIC_BASE, local APIC ID 0, destination ID 1 and fixed vector 0x51. It requires xAPIC enablement and an initially clear ICR destination, waits for idle delivery, writes and reads back ICR high, issues the physical fixed-delivery ICR low, and waits for completion. Return 0 is only local delivery completion, not acknowledgement. f1 is the original HIA EOI with highest-active-vector admission.

The independent observer starts a distinct AP via an expressly non-HIA INIT/SIPI trampoline. It checks actual APIC identity and distinct AP/BSP MSR, uses separate stacks, publishes AP readiness, requires hardware ISR on the AP, calls native HIA EOI, checks cleared ISR, and publishes receipt only after independent IRETQ. The BSP never enables interrupts and rejects local IRR/ISR for the tested vector. Both PC and Q35 run with two CPUs. Refusals cover bad base, stale MSR, wrong vector/destination, disabled local APIC, stale ICR high; independently assembled single-store NOP mutations cover high destination, low send and EOI.

This remains a narrow isolated two-CPU QEMU experiment, with a single sender and exclusive access to ICR. The AP startup, IDT, interrupt entry and IRETQ are not HIA. No production APIC authority, arbitrary APIC enumeration, SMP scheduler, cross-CPU TLB invalidation, Linux syscall or full Linux acceptance is claimed. The original 17 HOLD gates, toolchain lock and 422 syscall obligations are unchanged.

Initial candidate is unqualified until the new exact CI report is read. The local operator execution interface returned an internal error before launching an independent desktop run.
