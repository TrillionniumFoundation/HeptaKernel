# Isolated QEMU hardware-sampled CR3 predicate

In PC 32 MiB and Q35 64 MiB, an explicitly **non-HIA** observer reads
live CR3/CR0/CR4/IA32_EFER and CPUID MAXPHYADDR, passes them to the
selfhost ELF native HIA `cr3_admit` bytes, then checks unchanged live CR3.
Three altered copies must be rejected: CR0.WP=0, EFER.NXE=0, and CR3 bit 0.
An independent dishonest native HIA unconditional-admit fixture must visibly
reach a distinct bypass marker. Native original and boot symbol `.text`
hashes must agree. All four QEMU cases run via `make test-cr3-hw` inside
`make test`; the report is `build/cr3-hardware-report.json`.

This tests real hardware-sampled **inputs** to HIA Core v8. CPUID, RDMSR,
MOV CRx, serial output, 32-bit boot and debug exit are non-HIA. No HIA
privileged opcode, physical page-table provenance, atomics, root switching,
Linux syscall or full Linux closure is claimed. Existing boot.S stays.
The 17 full-acceptance gates and 422 syscall obligations stay HOLD.
